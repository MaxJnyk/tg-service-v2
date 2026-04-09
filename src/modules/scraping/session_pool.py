"""
Пул сессий — управляет жизненным циклом Telethon-клиентов с round-robin выбором.

Поддерживает busy-трекинг, FloodWait кулдаун, авто-деактивацию после 5 фейлов,
и anti-detect jitter перед каждым запросом.
"""

import asyncio
import logging
import random
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from telethon import TelegramClient

from src.core.exceptions import NoAvailableSessionError
from src.core.security import mask_phone
from src.infrastructure.database import async_session_factory
from src.modules.accounts.models import Proxy, TelegramSession
from src.modules.scraping.telethon_client import create_telethon_client

logger = logging.getLogger(__name__)

# Anti-detect: случайная задержка перед каждым запросом в Telegram
_JITTER_MIN = 0.5
_JITTER_MAX = 2.5


class SessionPool:
    def __init__(self, max_size: int = 20) -> None:
        self._pool: dict[str, TelegramClient] = {}  # session_id -> client
        self._max_size = max_size
        self._round_robin_index = 0
        self._lock = asyncio.Lock()  # Защищает мутации пула + round-robin
        self._busy: set[str] = set()  # session_id сессий, занятых сейчас

    async def get_session(self, role: str = "scrape", _retry_depth: int = 0) -> tuple[TelegramClient, TelegramSession]:
        """Получить активную сессию для роли. Создаёт клиент если его нет в пуле."""
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

            # Round-robin, пропускаем сессии занятые другими задачами
            async with self._lock:
                session = None
                for i in range(len(sessions)):
                    idx = (self._round_robin_index + i) % len(sessions)
                    candidate = sessions[idx]
                    if candidate.id not in self._busy:
                        session = candidate
                        self._round_robin_index = idx + 1
                        self._busy.add(session.id)
                        break
                if session is None:
                    # Все сессии заняты — разрешаем шаринг через round-robin
                    idx = self._round_robin_index % len(sessions)
                    self._round_robin_index += 1
                    session = sessions[idx]
                    self._busy.add(session.id)

            # Прокси — строгая привязка: каждая сессия ОБЯЗАНА использовать свою прокси.
            # Telegram трекает смену IP; без прокси светится IP сервера.
            proxy = None
            if session.proxy_id:
                proxy_result = await db.execute(
                    select(Proxy).where(Proxy.id == session.proxy_id, Proxy.is_active.is_(True))
                )
                proxy = proxy_result.scalar_one_or_none()
                if proxy is None:
                    logger.warning(
                        "Session %s has proxy_id=%s but proxy is inactive/missing — skipping to avoid IP leak",
                        mask_phone(session.phone), session.proxy_id,
                    )
                    # Пропускаем эту сессию, берём следующую (с защитой от рекурсии)
                    if _retry_depth >= 10:
                        raise NoAvailableSessionError("All sessions have dead proxies")
                    return await self.get_session(role=role, _retry_depth=_retry_depth + 1)

            elif session.proxy_id is None:
                logger.warning("Session %s has NO proxy assigned — connecting with server IP", mask_phone(session.phone))

        # Получить или создать клиент; переподключиться если коннект упал
        async with self._lock:
            existing = self._pool.get(session.id)
            if existing is not None and not existing.is_connected():
                logger.warning("Session %s lost connection, reconnecting", mask_phone(session.phone))
                try:
                    await existing.disconnect()
                except Exception:
                    pass
                del self._pool[session.id]
                existing = None

            if existing is None:
                client = create_telethon_client(session, proxy)
                await client.connect()
                if not await client.is_user_authorized():
                    logger.error("Session %s not authorized, marking as archived", mask_phone(session.phone))
                    await self._mark_session_status(session.id, "archived")
                    raise NoAvailableSessionError(f"Session {session.phone} not authorized")
                self._pool[session.id] = client
                logger.info("Connected session %s (pool size: %d)", mask_phone(session.phone), len(self._pool))

        # Anti-detect jitter после подключения (перед реальным API-вызовом)
        jitter = random.uniform(_JITTER_MIN, _JITTER_MAX)
        await asyncio.sleep(jitter)

        return self._pool[session.id], session

    async def release_session(self, session_id: str) -> None:
        """Вернуть сессию в пул (больше не занята)."""
        async with self._lock:
            self._busy.discard(session_id)

    async def mark_flood_wait(self, session_id: str, wait_seconds: int) -> None:
        """Отметить сессию на FloodWait кулдаун."""
        until = datetime.now(UTC).replace(microsecond=0) + timedelta(seconds=wait_seconds)
        await self._mark_session_flood(session_id, until)

        async with self._lock:
            self._busy.discard(session_id)
            if session_id in self._pool:
                del self._pool[session_id]

    async def mark_session_failed(self, session_id: str) -> None:
        """Увеличить счётчик ошибок; деактивировать после 5 фейлов."""
        async with async_session_factory() as db:
            result = await db.execute(
                select(TelegramSession).where(TelegramSession.id == session_id)
            )
            session = result.scalar_one_or_none()
            if session:
                session.fail_count += 1
                if session.fail_count >= 5:
                    session.status = "banned"
                    logger.warning("Session %s marked as banned after %d failures", mask_phone(session.phone), session.fail_count)
                    async with self._lock:
                        self._busy.discard(session_id)
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
        """Отключить все Telethon-клиенты (при shutdown)."""
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
