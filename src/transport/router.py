"""
Topic router — dispatches Kafka messages to registered handlers.
"""

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from src.transport.producer import KafkaResultProducer
from src.transport.schemas import TaskRequestSchema

logger = logging.getLogger(__name__)

Handler = Callable[[TaskRequestSchema, KafkaResultProducer], Awaitable[Any]]


class TopicRouter:
    def __init__(self) -> None:
        self._handlers: dict[str, Handler] = {}

    @property
    def handler_count(self) -> int:
        return len(self._handlers)

    def register(self, topic: str, handler: Handler) -> None:
        self._handlers[topic] = handler
        logger.info("Registered handler for topic: %s", topic)

    async def dispatch(
        self,
        topic: str,
        request: TaskRequestSchema,
        producer: KafkaResultProducer,
    ) -> None:
        handler = self._handlers.get(topic)
        if handler is None:
            logger.warning("No handler for topic %s, request_id=%s", topic, request.request_id)
            await producer.send_result(
                original_topic=topic,
                request=request,
                error=f"NO_HANDLER: topic {topic}",
            )
            return

        await handler(request, producer)
