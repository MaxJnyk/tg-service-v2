"""
Redis-based idempotency guard.
Prevents duplicate processing of the same request_id within a TTL window.
"""

import logging

from src.infrastructure.redis import get_redis

logger = logging.getLogger(__name__)

DEFAULT_TTL_SECONDS = 3600  # 1 hour


async def is_duplicate(request_id: str, ttl: int = DEFAULT_TTL_SECONDS) -> bool:
    """Check if request_id was already processed. If not, mark it."""
    redis = get_redis()
    key = f"idempotency:{request_id}"

    # SET NX: only sets if key does not exist
    was_set = await redis.set(key, "1", ex=ttl, nx=True)
    if was_set:
        return False  # First time — not a duplicate

    logger.warning("Duplicate request detected: %s", request_id)
    return True


async def clear_idempotency(request_id: str) -> None:
    """Clear idempotency key (e.g., on error that should be retried)."""
    redis = get_redis()
    await redis.delete(f"idempotency:{request_id}")
