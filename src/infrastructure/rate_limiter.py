"""
Redis-бейсд rate limiter для Telegram Bot API.

Двухуровневое скользящее окно: глобально (30 msg/sec) + по чату (20 msg/min).
Атомарный Lua-скрипт для check-and-acquire — нет race condition.
Безопасно для кластера: один Redis-ключ на операцию.
"""

import asyncio
import logging
import time

from redis.asyncio import Redis

logger = logging.getLogger(__name__)

# Telegram Bot API hard limits
_GLOBAL_LIMIT = 25          # msg/sec, консервативный (hard limit is 30)
_PER_CHAT_LIMIT = 1         # msg/sec per chat
_WINDOW_SEC = 1.0
_MAX_WAIT_SEC = 10.0        # give up after 10s waiting for slot

# Lua-скрипт: атомарный "check and acquire" для скользящего окна.
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
    Двухуровневый rate limiter с скользящим окном, основанный на Redis.

    Использует атомарный Lua-скрипт для check+acquire — безопасно при конкурентном доступе.

    Usage:
        await rate_limiter.acquire(chat_id="@channel")
        # ... send message ...
    """

    def __init__(self, redis: Redis) -> None:
        self._redis = redis
        self._script = redis.register_script(_ACQUIRE_LUA)

    async def acquire(self, chat_id: str) -> None:
        """Занять слот. Блокирует пока не освободится место (MAX_WAIT)."""
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
        global_key = "tg_rl:global"
        chat_key = f"tg_rl:chat:{chat_id}"
        window_start = now - _WINDOW_SEC
        member = f"{now}:{chat_id}"

        result = await self._script(
            keys=[global_key, chat_key],
            args=[window_start, now, _GLOBAL_LIMIT, _PER_CHAT_LIMIT, member],
        )
        return bool(result)
