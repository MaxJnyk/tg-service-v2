"""
Redis-backed rate limiter for Telegram Bot API.

Telegram limits:
  - Global: 30 messages/second across all chats
  - Per-chat: 1 message/second (Telegram silently drops/delays otherwise)

Uses sliding window via Redis sorted sets (ZADD/ZRANGEBYSCORE).
All workers share the same Redis → cluster-safe.
"""

import asyncio
import logging
import time

from redis.asyncio import Redis

logger = logging.getLogger(__name__)

# Telegram Bot API hard limits
_GLOBAL_LIMIT = 25          # msg/sec, conservative (hard limit is 30)
_PER_CHAT_LIMIT = 1         # msg/sec per chat
_WINDOW_SEC = 1.0
_MAX_WAIT_SEC = 10.0        # give up after 10s waiting for slot


class RateLimiter:
    """
    Two-level sliding-window rate limiter backed by Redis.

    Usage:
        await rate_limiter.acquire(chat_id="@channel")
        # ... send message ...
    """

    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def acquire(self, chat_id: str) -> None:
        """
        Block until both global and per-chat slots are available.

        Raises:
            asyncio.TimeoutError: if waited more than _MAX_WAIT_SEC
        """
        deadline = time.monotonic() + _MAX_WAIT_SEC
        while True:
            now = time.time()
            ok = await self._try_acquire(now, chat_id)
            if ok:
                return

            if time.monotonic() >= deadline:
                raise asyncio.TimeoutError(
                    f"Rate limit wait exceeded {_MAX_WAIT_SEC}s for chat={chat_id}"
                )

            await asyncio.sleep(0.05)  # 50ms polling

    async def _try_acquire(self, now: float, chat_id: str) -> bool:
        """
        Atomically check and record a slot in both global and per-chat windows.
        Returns True if acquired, False if either window is full.
        """
        global_key = "tg_rl:global"
        chat_key = f"tg_rl:chat:{chat_id}"
        window_start = now - _WINDOW_SEC
        member = str(now)

        pipe = self._redis.pipeline(transaction=True)
        # Clean old entries
        pipe.zremrangebyscore(global_key, "-inf", window_start)
        pipe.zremrangebyscore(chat_key, "-inf", window_start)
        # Count current window
        pipe.zcard(global_key)
        pipe.zcard(chat_key)
        results = await pipe.execute()

        global_count = results[2]
        chat_count = results[3]

        if global_count >= _GLOBAL_LIMIT or chat_count >= _PER_CHAT_LIMIT:
            return False

        # Add our slot
        pipe = self._redis.pipeline(transaction=True)
        pipe.zadd(global_key, {member: now})
        pipe.expire(global_key, 5)
        pipe.zadd(chat_key, {member: now})
        pipe.expire(chat_key, 5)
        await pipe.execute()
        return True
