"""
Kafka task consumer — subscribes to topics, deserializes, dispatches.

Key design decisions:
  - enable_auto_commit=True — safe with idempotency guard in handlers
  - Concurrent processing: up to CONSUMER_CONCURRENCY tasks in parallel via Semaphore
  - At-least-once delivery: idempotency guard prevents double-execution on redelivery
  - Scale horizontally: more replicas + Kafka partitions
  - On handler error: classify → send error result (don't block queue)
"""

import asyncio
import logging
import time
from typing import Any

import orjson
from aiokafka import AIOKafkaConsumer

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

    async def start(self) -> None:
        self._consumer = AIOKafkaConsumer(
            *self._topics,
            bootstrap_servers=self._bootstrap_servers,
            group_id=self._group_id,
            enable_auto_commit=True,
            auto_offset_reset="earliest",
            value_deserializer=self._deserialize,
        )
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
            await asyncio.gather(*self._tasks, return_exceptions=True)
        if self._consumer:
            await self._consumer.stop()
            logger.info("KafkaTaskConsumer stopped")

    @staticmethod
    def _deserialize(value: bytes) -> dict[str, Any]:
        return orjson.loads(value)

    async def consume_loop(self) -> None:
        """Concurrent consume loop with semaphore-based concurrency control.

        At-least-once + idempotency:
          - auto_commit=True (Kafka handles offsets)
          - Idempotency guard in each handler prevents double-execution
          - On crash: Kafka redelivers → idempotency guard skips duplicates

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

            try:
                request = TaskRequestSchema.model_validate(msg.value)
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
                    request_id = msg.value.get("request_id", "unknown") if isinstance(msg.value, dict) else "unknown"
                    callback = msg.value.get("callback_task_name") if isinstance(msg.value, dict) else None
                    fallback_request = TaskRequestSchema(
                        request_id=request_id,
                        callback_task_name=callback,
                        payload=msg.value if isinstance(msg.value, dict) else None,
                    )
                    await self._producer.send_result(
                        original_topic=topic,
                        request=fallback_request,
                        error=f"INTERNAL_ERROR: {exc}",
                    )
                except Exception as send_exc:
                    logger.exception("Failed to send error result: %s", send_exc)

            finally:
                elapsed = time.monotonic() - t0
                kafka_processing_duration.labels(topic=topic).observe(elapsed)
