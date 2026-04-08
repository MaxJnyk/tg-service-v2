"""
Repository for BotAccount, TelegramSession, Proxy CRUD operations.
"""

import logging
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.modules.accounts.models import BotAccount, Proxy, TelegramSession

logger = logging.getLogger(__name__)


class AccountRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._db = session

    # === Bot Accounts ===

    async def get_active_bots(self) -> list[BotAccount]:
        result = await self._db.execute(
            select(BotAccount).where(BotAccount.is_active.is_(True)).order_by(BotAccount.name)
        )
        return list(result.scalars().all())

    async def get_bot_by_id(self, bot_id: str) -> BotAccount | None:
        result = await self._db.execute(select(BotAccount).where(BotAccount.id == bot_id))
        return result.scalar_one_or_none()

    async def create_bot(self, **kwargs: Any) -> BotAccount:
        bot = BotAccount(**kwargs)
        self._db.add(bot)
        await self._db.flush()
        return bot

    async def update_bot(self, bot_id: str, **kwargs: Any) -> None:
        await self._db.execute(update(BotAccount).where(BotAccount.id == bot_id).values(**kwargs))

    # === Telegram Sessions ===

    async def get_active_sessions(self, role: str | None = None) -> list[TelegramSession]:
        q = select(TelegramSession).where(TelegramSession.status == "active")
        if role:
            q = q.where(TelegramSession.role == role)
        result = await self._db.execute(q.order_by(TelegramSession.phone))
        return list(result.scalars().all())

    async def get_session_by_phone(self, phone: str) -> TelegramSession | None:
        result = await self._db.execute(select(TelegramSession).where(TelegramSession.phone == phone))
        return result.scalar_one_or_none()

    async def create_session(self, **kwargs: Any) -> TelegramSession:
        session = TelegramSession(**kwargs)
        self._db.add(session)
        await self._db.flush()
        return session

    # === Proxies ===

    async def get_active_proxies(self) -> list[Proxy]:
        result = await self._db.execute(
            select(Proxy).where(Proxy.is_active.is_(True)).order_by(Proxy.response_time_ms.asc().nullslast())
        )
        return list(result.scalars().all())

    async def get_all_proxies(self) -> list[Proxy]:
        result = await self._db.execute(select(Proxy).order_by(Proxy.host))
        return list(result.scalars().all())

    async def create_proxy(self, **kwargs: Any) -> Proxy:
        proxy = Proxy(**kwargs)
        self._db.add(proxy)
        await self._db.flush()
        return proxy

    async def update_proxy(self, proxy_id: str, **kwargs: Any) -> None:
        await self._db.execute(update(Proxy).where(Proxy.id == proxy_id).values(**kwargs))
