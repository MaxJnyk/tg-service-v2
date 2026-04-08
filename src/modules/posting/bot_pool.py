"""
Bot pool — lazy-loads aiogram Bot instances from encrypted tokens in DB.
"""

import logging

import aiohttp
from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession

from sqlalchemy import select

from src.core.exceptions import NoAvailableBotError
from src.core.security import decrypt
from src.infrastructure.database import async_session_factory
from src.modules.accounts.models import BotAccount

logger = logging.getLogger(__name__)


class BotPool:
    def __init__(self, max_size: int = 50) -> None:
        self._pool: dict[str, Bot] = {}  # bot_account_id -> Bot
        self._max_size = max_size

    async def get_bot(self, bot_account_id: str) -> Bot:
        """Get or create a Bot instance by account ID."""
        if bot_account_id in self._pool:
            return self._pool[bot_account_id]

        async with async_session_factory() as session:
            result = await session.execute(
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
            session = AiohttpSession(connector=connector)
            bot = Bot(token=token, session=session)
            self._pool[bot_account_id] = bot
            logger.info("Loaded bot into pool: %s (pool size: %d)", account.name, len(self._pool))
            return bot

    async def get_bot_for_platform(self, platform_id: str) -> tuple[Bot, BotAccount]:
        """Get an active bot linked to a platform, or any active bot as fallback."""
        async with async_session_factory() as session:
            # Try platform-specific bot first
            result = await session.execute(
                select(BotAccount).where(
                    BotAccount.platform_id == platform_id,
                    BotAccount.is_active.is_(True),
                ).order_by(BotAccount.fail_count.asc(), BotAccount.last_used_at.asc().nullsfirst())
            )
            account = result.scalar_one_or_none()

            if not account:
                # Fallback: any active bot
                result = await session.execute(
                    select(BotAccount).where(
                        BotAccount.is_active.is_(True),
                    ).order_by(BotAccount.fail_count.asc(), BotAccount.last_used_at.asc().nullsfirst())
                )
                account = result.scalar_one_or_none()

            if not account:
                raise NoAvailableBotError()

            bot = await self.get_bot(account.id)
            return bot, account

    async def mark_bot_failed(self, bot_account_id: str) -> None:
        """Increment fail count; deactivate if too many failures."""
        async with async_session_factory() as session:
            result = await session.execute(
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
                await session.commit()

    async def close_all(self) -> None:
        """Close all bot sessions."""
        for bot_id, bot in self._pool.items():
            try:
                await bot.session.close()
            except Exception as exc:
                logger.warning("Error closing bot %s: %s", bot_id, exc)
        self._pool.clear()
        logger.info("Bot pool closed")
