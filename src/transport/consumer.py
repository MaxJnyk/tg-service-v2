"""
Kafka task consumer — subscribes to topics, deserializes, dispatches, manual commit.

Key design decisions:
  - enable_auto_commit=False — we commit AFTER successful processing
  - On handler error: classify → send error result → commit (don't lose offset)
  - group_id from config
"""

import asyncio
import logging
from typing import Any

from aiokafka import AIOKafkaConsumer

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
        self._semaphore = asyncio.Semaphore(100)  # Max 100 concurrent tasks

    async def start(self) -> None:
        self._consumer = AIOKafkaConsumer(
            *self._topics,
            bootstrap_servers=self._bootstrap_servers,
            group_id=self._group_id,
            enable_auto_commit=False,
            auto_offset_reset="earliest",
            value_deserializer=self._deserialize,
        )
        await self._consumer.start()
        self._running = True
        logger.info(
            "Connected to Kafka, listening topics: %s (group_id=%s)",
            self._topics,
            self._group_id,
        )

    async def stop(self) -> None:
        self._running = False
        if self._consumer:
            await self._consumer.stop()
            logger.info("KafkaTaskConsumer stopped")

    @staticmethod
    def _deserialize(value: bytes) -> dict[str, Any]:
        import json
        return json.loads(value.decode("utf-8"))

    async def _process_message(self, msg) -> None:
        """Process single message with semaphore-controlled concurrency."""
        async with self._semaphore:
            topic = msg.topic
            try:
                request = TaskRequestSchema.model_validate(msg.value)
                logger.info(
                    "Processing task: topic=%s request_id=%s",
                    topic,
                    request.request_id,
                )
                await self._router.dispatch(topic, request, self._producer)
            except Exception as exc:
                logger.exception("Error processing message from %s: %s", topic, exc)
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

    async def consume_loop(self) -> None:
        if not self._consumer:
            raise RuntimeError("Consumer not started")

        _MAX_PENDING = 100  # Matches semaphore — prevents unbounded task accumulation
        pending_tasks: set[asyncio.Task] = set()

        async for msg in self._consumer:
            if not self._running:
                break

            # Create task for concurrent processing (semaphore limits actual concurrency)
            task = asyncio.create_task(self._process_message(msg))
            pending_tasks.add(task)

            # Clean up completed tasks and commit their offsets
            done_tasks = {t for t in pending_tasks if t.done()}
            if done_tasks:
                pending_tasks -= done_tasks
                await self._consumer.commit()
                logger.debug("Committed %d completed tasks (pending=%d)", len(done_tasks), len(pending_tasks))

            # Back-pressure: wait for all tasks when we hit the cap
            # This prevents unbounded memory growth if Kafka produces faster than we process
            if len(pending_tasks) >= _MAX_PENDING:
                await asyncio.gather(*pending_tasks, return_exceptions=True)
                pending_tasks.clear()
                await self._consumer.commit()
                logger.debug("Committed full batch of %d messages", _MAX_PENDING)

        # Wait for remaining tasks before shutdown
        if pending_tasks:
            logger.info("Draining %d remaining tasks before shutdown", len(pending_tasks))
            await asyncio.gather(*pending_tasks, return_exceptions=True)
            await self._consumer.commit()
