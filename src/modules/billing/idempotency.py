"""
Redis-based идемпотентность.

Предотвращает повторную обработку того же request_id в рамках TTL-окна.
"""

import logging

from src.infrastructure.redis import get_redis

logger = logging.getLogger(__name__)

DEFAULT_TTL_SECONDS = 3600  # 1 час по умолчанию


async def is_duplicate(request_id: str, ttl: int = DEFAULT_TTL_SECONDS) -> bool:
    """Проверить был ли request_id уже обработан. Если нет — отметить."""
    redis = get_redis()
    key = f"idempotency:{request_id}"

    # SET NX: устанавливает только если ключ не существует
    was_set = await redis.set(key, "1", ex=ttl, nx=True)
    if was_set:
        return False  # Первый раз — не дубль

    logger.warning("Duplicate request detected: %s", request_id)
    return True


async def clear_idempotency(request_id: str) -> None:
    """Очистить ключ идемпотентности (например, при ошибке которую нужно ретраить)."""
    redis = get_redis()
    await redis.delete(f"idempotency:{request_id}")
