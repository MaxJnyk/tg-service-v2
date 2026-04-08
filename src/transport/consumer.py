"""
Kafka task consumer — subscribes to topics, deserializes, dispatches, manual commit.

Key design decisions:
  - enable_auto_commit=False — we commit AFTER successful processing
  - On handler error: classify → send error result → commit (don't lose offset)
  - group_id from config
"""

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

    async def consume_loop(self) -> None:
        if not self._consumer:
            raise RuntimeError("Consumer not started")

        async for msg in self._consumer:
            if not self._running:
                break

            topic = msg.topic
            try:
                request = TaskRequestSchema.model_validate(msg.value)
                logger.info(
                    "Received task: topic=%s request_id=%s callback=%s",
                    topic,
                    request.request_id,
                    request.callback_task_name,
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

            # Always commit — even on error (error result already sent)
            await self._consumer.commit()
