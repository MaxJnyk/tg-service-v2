"""
Redis-backed rate limiter for Telegram Bot API.

Telegram limits:
  - Global: 30 messages/second across all chats
  - Per-chat: 1 message/second (Telegram silently drops/delays otherwise)

Uses atomic Lua script for check-and-acquire in a single round-trip.
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

# Lua script: atomic check-and-acquire (no race condition between check and add)
_ACQUIRE_LUA = """
local global_key = KEYS[1]
local chat_key   = KEYS[2]
local window_start  = tonumber(ARGV[1])
local now           = tonumber(ARGV[2])
local global_limit  = tonumber(ARGV[3])
local chat_limit    = tonumber(ARGV[4])
local member        = ARGV[5]

-- Clean old entries
redis.call('ZREMRANGEBYSCORE', global_key, '-inf', window_start)
redis.call('ZREMRANGEBYSCORE', chat_key, '-inf', window_start)

-- Check counts
local global_count = redis.call('ZCARD', global_key)
local chat_count   = redis.call('ZCARD', chat_key)

if global_count >= global_limit or chat_count >= chat_limit then
    return 0
end

-- Add our slot (atomic with the check above)
redis.call('ZADD', global_key, now, member)
redis.call('EXPIRE', global_key, 5)
redis.call('ZADD', chat_key, now, member)
redis.call('EXPIRE', chat_key, 5)
return 1
"""


class RateLimiter:
    """
    Two-level sliding-window rate limiter backed by Redis.

    Uses a single Lua script for atomic check+acquire — safe under concurrency.

    Usage:
        await rate_limiter.acquire(chat_id="@channel")
        # ... send message ...
    """

    def __init__(self, redis: Redis) -> None:
        self._redis = redis
        self._script = redis.register_script(_ACQUIRE_LUA)

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
        Atomically check and record a slot via Lua script.
        Single Redis round-trip — no race condition.
        """
        global_key = "tg_rl:global"
        chat_key = f"tg_rl:chat:{chat_id}"
        window_start = now - _WINDOW_SEC
        # Unique member: timestamp + chat_id to avoid collisions in sorted set
        member = f"{now}:{chat_id}"

        result = await self._script(
            keys=[global_key, chat_key],
            args=[window_start, now, _GLOBAL_LIMIT, _PER_CHAT_LIMIT, member],
        )
        return bool(result)
