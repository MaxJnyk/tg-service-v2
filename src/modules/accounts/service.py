"""
Account service — high-level operations for bot/session/proxy management.
Used by CLI and internally by posting/scraping modules.
"""

import logging

from src.core.security import encrypt
from src.infrastructure.database import async_session_factory
from src.modules.accounts.repository import AccountRepository

logger = logging.getLogger(__name__)


class AccountService:
    @staticmethod
    async def list_bots() -> list[dict]:
        async with async_session_factory() as db:
            repo = AccountRepository(db)
            bots = await repo.get_active_bots()
            return [
                {
                    "id": b.id,
                    "name": b.name,
                    "platform_id": b.platform_id,
                    "is_active": b.is_active,
                    "fail_count": b.fail_count,
                }
                for b in bots
            ]

    @staticmethod
    async def add_bot(name: str, token: str, platform_id: str | None = None) -> str:
        encrypted_token = encrypt(token)
        async with async_session_factory() as db:
            repo = AccountRepository(db)
            bot = await repo.create_bot(
                name=name,
                bot_token=encrypted_token,
                platform_id=platform_id,
            )
            await db.commit()
            logger.info("Added bot: %s (id=%s)", name, bot.id)
            return bot.id

    @staticmethod
    async def list_sessions(role: str | None = None) -> list[dict]:
        async with async_session_factory() as db:
            repo = AccountRepository(db)
            sessions = await repo.get_active_sessions(role=role)
            return [
                {
                    "id": s.id,
                    "phone": s.phone,
                    "status": s.status,
                    "role": s.role,
                    "proxy_id": s.proxy_id,
                    "fail_count": s.fail_count,
                }
                for s in sessions
            ]

    @staticmethod
    async def import_session(
        phone: str,
        session_string: str,
        api_id: int,
        api_hash: str,
        device_info: dict | None = None,
        proxy_id: str | None = None,
        role: str = "scrape",
    ) -> str:
        encrypted_session = encrypt(session_string)
        async with async_session_factory() as db:
            repo = AccountRepository(db)
            existing = await repo.get_session_by_phone(phone)
            if existing:
                logger.warning("Session for %s already exists, skipping", phone)
                return existing.id

            session = await repo.create_session(
                phone=phone,
                session_string=encrypted_session,
                api_id=api_id,
                api_hash=api_hash,
                device_info=device_info or {},
                proxy_id=proxy_id,
                role=role,
            )
            await db.commit()
            logger.info("Imported session: %s (id=%s, role=%s)", phone, session.id, role)
            return session.id

    @staticmethod
    async def list_proxies() -> list[dict]:
        async with async_session_factory() as db:
            repo = AccountRepository(db)
            proxies = await repo.get_all_proxies()
            return [
                {
                    "id": p.id,
                    "host": p.host,
                    "port": p.port,
                    "protocol": p.protocol,
                    "country_code": p.country_code,
                    "is_active": p.is_active,
                    "response_time_ms": p.response_time_ms,
                    "fail_count": p.fail_count,
                }
                for p in proxies
            ]

    @staticmethod
    async def add_proxy(
        host: str,
        port: int,
        protocol: str = "socks5",
        username: str | None = None,
        password: str | None = None,
        country_code: str | None = None,
    ) -> str:
        async with async_session_factory() as db:
            repo = AccountRepository(db)
            proxy = await repo.create_proxy(
                host=host,
                port=port,
                protocol=protocol,
                username=username,
                password=password,
                country_code=country_code,
            )
            await db.commit()
            logger.info("Added proxy: %s:%d (id=%s)", host, port, proxy.id)
            return proxy.id
