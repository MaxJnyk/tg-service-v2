"""
Redis connection pool for idempotency, rate limiting, caching.
"""

import logging

from redis.asyncio import ConnectionPool, Redis

from src.config import settings

logger = logging.getLogger(__name__)

_pool: ConnectionPool | None = None


def get_redis_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        _pool = ConnectionPool.from_url(
            settings.REDIS_URL,
            max_connections=20,
            decode_responses=True,
        )
    return _pool


def get_redis() -> Redis:
    return Redis(connection_pool=get_redis_pool())


async def close_redis() -> None:
    global _pool
    if _pool:
        await _pool.aclose()
        _pool = None
        logger.info("Redis connection pool closed")
