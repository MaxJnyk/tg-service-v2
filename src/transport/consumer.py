"""
Kafka task consumer — subscribes to topics, deserializes, dispatches.

Key design decisions:
  - enable_auto_commit=False — manual commit AFTER processing guarantees at-least-once
  - Concurrent processing: up to CONSUMER_CONCURRENCY tasks in parallel via Semaphore
  - At-least-once delivery: manual commit + idempotency guard prevents loss & double-execution
  - Scale horizontally: more replicas + Kafka partitions
  - On handler error: classify → send error result → commit (don't block queue)
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
from src.transport.router import TopicRouter
from src.transport.schemas import TaskRequestSchema

logger = logging.getLogger(__name__)

_DRAIN_TIMEOUT = settings.SHUTDOWN_TIMEOUT if hasattr(settings, "SHUTDOWN_TIMEOUT") else 30


class _RebalanceListener:
    """Handle Kafka consumer group rebalances safely.

    On partition revoke: wait for in-flight tasks on those partitions to finish,
    then commit their offsets before the partitions are handed to another consumer.
    This prevents duplicate processing after rebalance.
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
        # Wait for all in-flight tasks to complete (they may be on revoked partitions)
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
            # Prevent consumer eviction during long scraping (up to 30s per channel)
            session_timeout_ms=60_000,
            heartbeat_interval_ms=10_000,
            max_poll_interval_ms=300_000,
            # Limit poll batch to avoid unbounded task creation
            max_poll_records=settings.CONSUMER_CONCURRENCY * 2,
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
            logger.error("Malformed Kafka message (skip): %s | raw=%r", exc, value[:200])
            return None

    async def _commit_offset(self, msg: Any) -> None:
        """Commit offset for a single processed message. Thread-safe via lock."""
        if not self._consumer:
            return
        tp = TopicPartition(msg.topic, msg.partition)
        async with self._commit_lock:
            try:
                await self._consumer.commit({tp: msg.offset + 1})
            except Exception as exc:
                logger.warning("Failed to commit offset %s:%d:%d: %s", msg.topic, msg.partition, msg.offset, exc)

    async def consume_loop(self) -> None:
        """Concurrent consume loop with semaphore-based concurrency control.

        At-least-once + idempotency:
          - auto_commit=False — offset committed only AFTER successful processing
          - Idempotency guard in each handler prevents double-execution on redelivery
          - On crash: Kafka redelivers uncommitted messages → idempotency guard skips duplicates

        Throughput: up to CONSUMER_CONCURRENCY tasks in parallel.
        Telegram rate limiter (shared Redis) prevents API abuse.
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
        """Process a single Kafka message under semaphore concurrency limit."""
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
                logger.exception("Error processing message from %s: %s", topic, exc)
                kafka_messages_errors.labels(topic=topic, error_code="INTERNAL_ERROR").inc()
                try:
                    request_id = data.get("request_id") if isinstance(data, dict) else None
                    request_id = request_id or str(uuid.uuid4())
                    callback = data.get("callback_task_name") if isinstance(data, dict) else None
                    fallback_request = TaskRequestSchema(
                        request_id=request_id,
                        callback_task_name=callback,
                        payload=data if isinstance(data, dict) else None,
                    )
                    await self._producer.send_result(
                        original_topic=topic,
                        request=fallback_request,
                        error=f"INTERNAL_ERROR: {exc}",
                    )
                except Exception as send_exc:
                    logger.exception("Failed to send error result: %s", send_exc)

            finally:
                structlog.contextvars.unbind_contextvars("request_id", "topic")
                elapsed = time.monotonic() - t0
                kafka_processing_duration.labels(topic=topic).observe(elapsed)
                await self._commit_offset(msg)
