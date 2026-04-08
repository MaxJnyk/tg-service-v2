"""
Session pool — manages Telethon client lifecycle with round-robin selection.
"""

import logging
from datetime import UTC, datetime

from sqlalchemy import select, update
from telethon import TelegramClient

from src.core.exceptions import NoAvailableSessionError
from src.infrastructure.database import async_session_factory
from src.modules.accounts.models import Proxy, TelegramSession
from src.modules.scraping.telethon_client import create_telethon_client

logger = logging.getLogger(__name__)


class SessionPool:
    def __init__(self, max_size: int = 20) -> None:
        self._pool: dict[str, TelegramClient] = {}  # session_id -> client
        self._max_size = max_size
        self._round_robin_index = 0

    async def get_session(self, role: str = "scrape") -> tuple[TelegramClient, TelegramSession]:
        """Get an active session for the given role. Creates client if not in pool."""
        async with async_session_factory() as db:
            result = await db.execute(
                select(TelegramSession)
                .where(
                    TelegramSession.status == "active",
                    TelegramSession.role == role,
                    (TelegramSession.flood_wait_until.is_(None))
                    | (TelegramSession.flood_wait_until < datetime.now(UTC)),
                )
                .order_by(TelegramSession.fail_count.asc(), TelegramSession.last_used_at.asc().nullsfirst())
            )
            sessions = list(result.scalars().all())

            if not sessions:
                raise NoAvailableSessionError(f"No active sessions with role={role}")

            # Round-robin
            idx = self._round_robin_index % len(sessions)
            self._round_robin_index += 1
            session = sessions[idx]

            # Load proxy if linked
            proxy = None
            if session.proxy_id:
                proxy_result = await db.execute(
                    select(Proxy).where(Proxy.id == session.proxy_id, Proxy.is_active.is_(True))
                )
                proxy = proxy_result.scalar_one_or_none()

        # Get or create client
        if session.id not in self._pool:
            client = create_telethon_client(session, proxy)
            await client.connect()
            if not await client.is_user_authorized():
                logger.error("Session %s not authorized, marking as archived", session.phone)
                await self._mark_session_status(session.id, "archived")
                raise NoAvailableSessionError(f"Session {session.phone} not authorized")
            self._pool[session.id] = client
            logger.info("Connected session %s (pool size: %d)", session.phone, len(self._pool))

        return self._pool[session.id], session

    async def mark_flood_wait(self, session_id: str, wait_seconds: int) -> None:
        """Mark session with flood wait cooldown."""
        until = datetime.now(UTC).replace(microsecond=0)
        from datetime import timedelta
        until += timedelta(seconds=wait_seconds)
        await self._mark_session_flood(session_id, until)

        if session_id in self._pool:
            del self._pool[session_id]

    async def mark_session_failed(self, session_id: str) -> None:
        """Increment fail count; deactivate after 5 failures."""
        async with async_session_factory() as db:
            result = await db.execute(
                select(TelegramSession).where(TelegramSession.id == session_id)
            )
            session = result.scalar_one_or_none()
            if session:
                session.fail_count += 1
                if session.fail_count >= 5:
                    session.status = "banned"
                    logger.warning("Session %s marked as banned after %d failures", session.phone, session.fail_count)
                    if session_id in self._pool:
                        del self._pool[session_id]
                await db.commit()

    async def mark_used(self, session_id: str) -> None:
        async with async_session_factory() as db:
            await db.execute(
                update(TelegramSession)
                .where(TelegramSession.id == session_id)
                .values(last_used_at=datetime.now(UTC))
            )
            await db.commit()

    async def close_all(self) -> None:
        """Disconnect all Telethon clients."""
        for sid, client in self._pool.items():
            try:
                await client.disconnect()
            except Exception as exc:
                logger.warning("Error disconnecting session %s: %s", sid, exc)
        self._pool.clear()
        logger.info("Session pool closed")

    @staticmethod
    async def _mark_session_status(session_id: str, status: str) -> None:
        async with async_session_factory() as db:
            await db.execute(
                update(TelegramSession)
                .where(TelegramSession.id == session_id)
                .values(status=status)
            )
            await db.commit()

    @staticmethod
    async def _mark_session_flood(session_id: str, until: datetime) -> None:
        async with async_session_factory() as db:
            await db.execute(
                update(TelegramSession)
                .where(TelegramSession.id == session_id)
                .values(flood_wait_until=until)
            )
            await db.commit()
