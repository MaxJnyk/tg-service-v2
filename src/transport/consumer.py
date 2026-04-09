"""
Kafka consumer — подписывается на топики, десериализует, диспатчит обработчикам.

Ключевые решения:
  - enable_auto_commit=False — коммит вручную ПОСЛЕ обработки = at-least-once
  - Конкурентность: до CONSUMER_CONCURRENCY задач параллельно через Semaphore
  - Идемпотентность: ручной коммит + Redis-гард = нет потерь и дублей
  - Горизонтальное масштабирование: больше реплик + Kafka-partitions
  - При ошибке: шлём error result → коммитим (не блокируем очередь)
"""

import asyncio
import logging
import time
import uuid
from typing import Any

import orjson
import structlog
from aiokafka import AIOKafkaConsumer, TopicPartition

from src.config import settings
from src.core.metrics import (
    kafka_messages_errors,
    kafka_messages_processed,
    kafka_messages_received,
    kafka_processing_duration,
)
from src.transport.producer import KafkaResultProducer
from src.core.security import redact_sensitive
from src.transport.router import TopicRouter
from src.transport.schemas import TaskRequestSchema

logger = logging.getLogger(__name__)

_DRAIN_TIMEOUT = settings.SHUTDOWN_TIMEOUT if hasattr(settings, "SHUTDOWN_TIMEOUT") else 30


class _RebalanceListener:
    """Обработка ребаланса Kafka consumer group.

    При отзыве partitions: ждём завершения in-flight задач на этих partitions,
    потом коммитим их оффсеты. Это предотвращает дубли после ребаланса.
    """

    def __init__(self, consumer: "KafkaTaskConsumer") -> None:
        self._consumer = consumer

    async def on_partitions_revoked(self, revoked: set[TopicPartition]) -> None:
        if not revoked:
            return
        logger.info(
            "Partitions revoked: %s — draining %d in-flight tasks",
            [f"{tp.topic}:{tp.partition}" for tp in revoked],
            len(self._consumer._tasks),
        )
        # Ждём завершения всех in-flight задач (могут быть на отозванных partitions)
        if self._consumer._tasks:
            done, pending = await asyncio.wait(
                self._consumer._tasks,
                timeout=_DRAIN_TIMEOUT,
            )
            if pending:
                logger.warning("%d tasks still running after drain timeout, cancelling", len(pending))
                for t in pending:
                    t.cancel()
                await asyncio.gather(*pending, return_exceptions=True)

    async def on_partitions_assigned(self, assigned: set[TopicPartition]) -> None:
        logger.info(
            "Partitions assigned: %s",
            [f"{tp.topic}:{tp.partition}" for tp in assigned],
        )


class KafkaTaskConsumer:
    def __init__(
        self,
        bootstrap_servers: str,
        group_id: str,
        topics: list[str],
        router: TopicRouter,
        producer: KafkaResultProducer,
    ) -> None:
        self._bootstrap_servers = bootstrap_servers
        self._group_id = group_id
        self._topics = topics
        self._router = router
        self._producer = producer
        self._consumer: AIOKafkaConsumer | None = None
        self._running = False
        self._semaphore = asyncio.Semaphore(settings.CONSUMER_CONCURRENCY or 1)
        self._tasks: set[asyncio.Task] = set()
        self._commit_lock = asyncio.Lock()

    async def start(self) -> None:
        listener = _RebalanceListener(self)
        self._consumer = AIOKafkaConsumer(
            bootstrap_servers=self._bootstrap_servers,
            group_id=self._group_id,
            enable_auto_commit=False,
            auto_offset_reset="earliest",
            # Не даём Kafka выкинуть consumer во время долгого парсинга (до 30с на канал)
            session_timeout_ms=60_000,
            heartbeat_interval_ms=10_000,
            max_poll_interval_ms=300_000,
            # Ограничиваем размер батча чтобы не плодить задачи без контроля
            max_poll_records=settings.CONSUMER_CONCURRENCY * 2,
            # Ограничиваем fetch чтобы не жрать память на гигантских сообщениях
            max_partition_fetch_bytes=1_048_576,  # 1 MB
        )
        self._consumer.subscribe(self._topics, listener=listener)
        await self._consumer.start()
        self._running = True
        logger.info(
            "Connected to Kafka, listening topics: %s (group_id=%s, concurrency=%d)",
            self._topics,
            self._group_id,
            settings.CONSUMER_CONCURRENCY,
        )

    async def stop(self) -> None:
        self._running = False
        if self._tasks:
            logger.info("Waiting for %d in-flight tasks to finish...", len(self._tasks))
            done, pending = await asyncio.wait(self._tasks, timeout=_DRAIN_TIMEOUT)
            if pending:
                logger.warning("Force-cancelling %d tasks after timeout", len(pending))
                for t in pending:
                    t.cancel()
                await asyncio.gather(*pending, return_exceptions=True)
        if self._consumer:
            await self._consumer.stop()
            logger.info("KafkaTaskConsumer stopped")

    @staticmethod
    def _deserialize(value: bytes) -> dict[str, Any] | None:
        try:
            return orjson.loads(value)
        except Exception as exc:
            logger.error("Malformed Kafka message (skip): %s | length=%d", exc, len(value))
            return None

    async def _commit_offset(self, msg: Any) -> None:
        """Коммит оффсета для одного обработанного сообщения. Потокобезопасно через lock."""
        if not self._consumer:
            return
        tp = TopicPartition(msg.topic, msg.partition)
        async with self._commit_lock:
            try:
                await self._consumer.commit({tp: msg.offset + 1})
            except Exception as exc:
                logger.warning("Failed to commit offset %s:%d:%d: %s", msg.topic, msg.partition, msg.offset, exc)

    async def consume_loop(self) -> None:
        """Конкурентный consume loop с контролем через Semaphore.

        At-least-once + идемпотентность:
          - auto_commit=False — оффсет коммитим только ПОСЛЕ обработки
          - Идемпотентность в каждом handler'e защищает от повторной обработки
          - При краше: Kafka передоставляет → идемпотентность скипает дубли

        Пропускная способность: до CONSUMER_CONCURRENCY задач параллельно.
        Rate limiter Telegram (через Redis) защищает от злоупотребления API.
        """
        if not self._consumer:
            raise RuntimeError("Consumer not started")

        async for msg in self._consumer:
            if not self._running:
                break

            task = asyncio.create_task(self._process_message(msg))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    async def _process_message(self, msg: Any) -> None:
        """Обработка одного Kafka-сообщения под контролем semaphore."""
        async with self._semaphore:
            topic = msg.topic
            kafka_messages_received.labels(topic=topic).inc()
            t0 = time.monotonic()

            data: dict[str, Any] | None = None
            try:
                data = self._deserialize(msg.value)
                if data is None:
                    kafka_messages_errors.labels(topic=topic, error_code="MALFORMED_JSON").inc()
                    return
                request = TaskRequestSchema.model_validate(data)
                structlog.contextvars.bind_contextvars(request_id=request.request_id, topic=topic)
                logger.info(
                    "Processing task: topic=%s request_id=%s",
                    topic,
                    request.request_id,
                )
                await self._router.dispatch(topic, request, self._producer)
                kafka_messages_processed.labels(topic=topic).inc()

            except Exception as exc:
                safe_error = redact_sensitive(str(exc))
                logger.error("Error processing message from %s: %s", topic, safe_error)
                kafka_messages_errors.labels(topic=topic, error_code="INTERNAL_ERROR").inc()
                try:
                    request_id = data.get("request_id") if isinstance(data, dict) else None
                    request_id = request_id or str(uuid.uuid4())
                    callback = data.get("callback_task_name") if isinstance(data, dict) else None
                    fallback_request = TaskRequestSchema(
                        request_id=request_id,
                        callback_task_name=callback,
                        payload=None,
                    )
                    await self._producer.send_result(
                        original_topic=topic,
                        request=fallback_request,
                        error=f"INTERNAL_ERROR: {safe_error}",
                    )
                except Exception as send_exc:
                    logger.error("Failed to send error result: %s", redact_sensitive(str(send_exc)))

            finally:
                structlog.contextvars.unbind_contextvars("request_id", "topic")
                elapsed = time.monotonic() - t0
                kafka_processing_duration.labels(topic=topic).observe(elapsed)
                await self._commit_offset(msg)
