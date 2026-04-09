"""
Kafka producer — отправляет TaskResultSchema обратно в result-топики.

Использует orjson для быстрой сериализации. Имя result-топика
строится как tad_{original_topic}_result.
"""

import logging
from typing import Any

import orjson
from aiokafka import AIOKafkaProducer

from src.transport.schemas import TaskRequestSchema, TaskResultSchema

logger = logging.getLogger(__name__)


class KafkaResultProducer:
    def __init__(self, bootstrap_servers: str) -> None:
        self._bootstrap_servers = bootstrap_servers
        self._producer: AIOKafkaProducer | None = None

    async def start(self) -> None:
        self._producer = AIOKafkaProducer(
            bootstrap_servers=self._bootstrap_servers,
            value_serializer=lambda v: orjson.dumps(v),
        )
        await self._producer.start()
        logger.info("KafkaResultProducer started, servers=%s", self._bootstrap_servers)

    async def stop(self) -> None:
        if self._producer:
            await self._producer.stop()
            logger.info("KafkaResultProducer остановлен")

    def _make_result_topic(self, original_topic: str) -> str:
        """scrape_platform -> tad_scrape_platform_result"""
        return f"tad_{original_topic}_result"

    async def send_result(
        self,
        original_topic: str,
        request: TaskRequestSchema,
        payload: Any | None = None,
        error: str | None = None,
    ) -> None:
        if not self._producer:
            raise RuntimeError("Producer not started")

        result = TaskResultSchema(
            request_id=request.request_id,
            callback_task_name=request.callback_task_name,
            request_payload=request.payload,
            payload=payload,
            error=error,
        )

        topic = request.result_topic or self._make_result_topic(original_topic)
        await self._producer.send_and_wait(topic, result.model_dump(mode="json"))

        if error:
            logger.warning("Sent error result to %s: request_id=%s error=%s", topic, request.request_id, error)
        else:
            logger.info("Sent result to %s: request_id=%s", topic, request.request_id)
