"""
Kafka handler for scraping topic:
  - scrape_platform

Parses PlatformSchema from payload, calls ScrapingService, sends result.
"""

import logging

from src.core.exceptions import TelegramServiceError
from src.modules.scraping.service import ScrapingService
from src.transport.producer import KafkaResultProducer
from src.transport.schemas import TaskRequestSchema

logger = logging.getLogger(__name__)


def create_scraping_handlers(scraping_service: ScrapingService) -> dict:
    """Create scraping handler functions."""

    async def handle_scrape_platform(
        request: TaskRequestSchema,
        producer: KafkaResultProducer,
    ) -> None:
        payload = request.payload or {}

        # Extract platform info — compatible with ScrapperTaskSchema
        platform = payload.get("platform", payload)
        url = platform.get("url", "")
        platform_id = str(platform.get("id", ""))

        # Extract username from URL
        username = url.strip("/").split("/")[-1] if url else ""
        if not username:
            await producer.send_result(
                original_topic="scrape_platform",
                request=request,
                error="INVALID_PAYLOAD: platform url is required",
            )
            return

        try:
            result = await scraping_service.scrape_platform(
                username=username,
                platform_id=platform_id,
            )
            await producer.send_result(
                original_topic="scrape_platform",
                request=request,
                payload=result,
            )
        except TelegramServiceError as exc:
            logger.error("scrape_platform failed: %s (code=%s)", exc, exc.error_code)
            await producer.send_result(
                original_topic="scrape_platform",
                request=request,
                error=f"{exc.error_code}: {exc}",
            )

    return {
        "scrape_platform": handle_scrape_platform,
    }
