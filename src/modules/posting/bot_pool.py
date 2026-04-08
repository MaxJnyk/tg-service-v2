"""
Bot pool — lazy-loads aiogram Bot instances from encrypted tokens in DB.

LRU eviction: when pool exceeds max_size, the least recently used bot
(oldest access) is closed and removed.
"""

import logging
import time
from collections import OrderedDict

import aiohttp
from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession

from sqlalchemy import select

from src.core.exceptions import NoAvailableBotError
from src.core.security import decrypt
from src.infrastructure.database import async_session_factory
from src.modules.accounts.models import BotAccount

logger = logging.getLogger(__name__)


_PLATFORM_CACHE_TTL = 60  # seconds


class BotPool:
    def __init__(self, max_size: int = 50) -> None:
        self._pool: OrderedDict[str, Bot] = OrderedDict()  # bot_account_id -> Bot (LRU order)
        self._max_size = max_size
        self._platform_cache: dict[str, tuple[BotAccount, float]] = {}  # platform_id -> (account, timestamp)

    async def get_bot(self, bot_account_id: str) -> Bot:
        """Get or create a Bot instance by account ID."""
        if bot_account_id in self._pool:
            self._pool.move_to_end(bot_account_id)
            return self._pool[bot_account_id]

        async with async_session_factory() as db_session:
            result = await db_session.execute(
                select(BotAccount).where(
                    BotAccount.id == bot_account_id,
                    BotAccount.is_active.is_(True),
                )
            )
            account = result.scalar_one_or_none()
            if not account:
                raise ValueError(f"Bot account {bot_account_id} not found or inactive")

            token = decrypt(account.bot_token)
            connector = aiohttp.TCPConnector(resolver=aiohttp.ThreadedResolver())
            aio_session = AiohttpSession(connector=connector)
            bot = Bot(token=token, session=aio_session)

            # Evict LRU bot if pool is full
            while len(self._pool) >= self._max_size:
                evicted_id, evicted_bot = self._pool.popitem(last=False)
                try:
                    await evicted_bot.session.close()
                except Exception as exc:
                    logger.warning("Error closing evicted bot %s: %s", evicted_id, exc)
                logger.info("Evicted LRU bot %s from pool", evicted_id)

            self._pool[bot_account_id] = bot
            logger.info("Loaded bot into pool: %s (pool size: %d/%d)", account.name, len(self._pool), self._max_size)
            return bot

    async def get_bot_for_platform(self, platform_id: str) -> tuple[Bot, BotAccount]:
        """Get an active bot linked to a platform, or any active bot as fallback.

        Uses an in-memory TTL cache to avoid repeated DB lookups.
        """
        now = time.monotonic()
        cached = self._platform_cache.get(platform_id)
        if cached is not None:
            account, ts = cached
            if now - ts < _PLATFORM_CACHE_TTL and account.is_active:
                bot = await self.get_bot(account.id)
                return bot, account
            del self._platform_cache[platform_id]

        async with async_session_factory() as db_session:
            # Try platform-specific bot first
            result = await db_session.execute(
                select(BotAccount).where(
                    BotAccount.platform_id == platform_id,
                    BotAccount.is_active.is_(True),
                ).order_by(BotAccount.fail_count.asc(), BotAccount.last_used_at.asc().nullsfirst())
            )
            account = result.scalar_one_or_none()

            if not account:
                # Fallback: any active bot
                result = await db_session.execute(
                    select(BotAccount).where(
                        BotAccount.is_active.is_(True),
                    ).order_by(BotAccount.fail_count.asc(), BotAccount.last_used_at.asc().nullsfirst())
                )
                account = result.scalar_one_or_none()

            if not account:
                raise NoAvailableBotError()

            self._platform_cache[platform_id] = (account, now)
            bot = await self.get_bot(account.id)
            return bot, account

    async def mark_bot_failed(self, bot_account_id: str) -> None:
        """Increment fail count; deactivate if too many failures."""
        # Invalidate platform cache entries pointing to this bot
        to_evict = [pid for pid, (acc, _) in self._platform_cache.items() if acc.id == bot_account_id]
        for pid in to_evict:
            del self._platform_cache[pid]

        async with async_session_factory() as db_session:
            result = await db_session.execute(
                select(BotAccount).where(BotAccount.id == bot_account_id)
            )
            account = result.scalar_one_or_none()
            if account:
                account.fail_count += 1
                if account.fail_count >= 5:
                    account.is_active = False
                    logger.warning("Bot %s deactivated after %d failures", account.name, account.fail_count)
                    if bot_account_id in self._pool:
                        del self._pool[bot_account_id]
                await db_session.commit()

    async def close_all(self) -> None:
        """Close all bot sessions."""
        for bot_id, bot in self._pool.items():
            try:
                await bot.session.close()
            except Exception as exc:
                logger.warning("Error closing bot %s: %s", bot_id, exc)
        self._pool.clear()
        logger.info("Bot pool closed")
