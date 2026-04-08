"""
Kafka handler for scraping topic:
  - scrape_platform

Parses PlatformSchema from payload, calls ScrapingService, sends result.
"""

import logging

from src.core.exceptions import NoAvailableSessionError, TelegramServiceError
from src.infrastructure.redis import get_redis
from src.modules.scraping.service import ScrapingService
from src.transport.producer import KafkaResultProducer
from src.transport.schemas import TaskRequestSchema

logger = logging.getLogger(__name__)

_IDEMPOTENCY_TTL = 86400  # 24h


async def _check_idempotency(request_id: str) -> bool:
    """Return True if already processed (duplicate)."""
    key = f"tg_idem:scrape:{request_id}"
    result = await get_redis().set(key, "1", nx=True, ex=_IDEMPOTENCY_TTL)
    return result is None  # None → key existed → duplicate


def create_scraping_handlers(scraping_service: ScrapingService) -> dict:
    """Create scraping handler functions."""

    async def handle_scrape_platform(
        request: TaskRequestSchema,
        producer: KafkaResultProducer,
    ) -> None:
        if await _check_idempotency(str(request.request_id)):
            logger.warning("scrape_platform: duplicate request_id=%s, skipping", request.request_id)
            return

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
        except NoAvailableSessionError as exc:
            logger.error("scrape_platform: no active session available")
            await producer.send_result(
                original_topic="scrape_platform",
                request=request,
                error=f"[{exc.error_code}] {exc}",
            )
        except TelegramServiceError as exc:
            logger.error("scrape_platform failed: %s (code=%s)", exc, exc.error_code)
            await producer.send_result(
                original_topic="scrape_platform",
                request=request,
                error=f"[{exc.error_code}] {exc}",
            )

    return {
        "scrape_platform": handle_scrape_platform,
    }
