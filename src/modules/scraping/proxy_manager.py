"""
Proxy manager — health check and rotation for SOCKS5/HTTP proxies.
"""

import asyncio
import logging
from datetime import datetime

from sqlalchemy import select, update

from src.infrastructure.database import async_session_factory
from src.modules.accounts.models import Proxy

logger = logging.getLogger(__name__)


class ProxyManager:
    @staticmethod
    async def check_proxy(proxy: Proxy) -> bool:
        """Check if proxy is alive by connecting to Telegram's DC."""
        try:
            start = asyncio.get_event_loop().time()
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(proxy.host, proxy.port),
                timeout=10.0,
            )
            writer.close()
            await writer.wait_closed()
            elapsed_ms = int((asyncio.get_event_loop().time() - start) * 1000)

            async with async_session_factory() as db:
                await db.execute(
                    update(Proxy)
                    .where(Proxy.id == proxy.id)
                    .values(
                        is_active=True,
                        response_time_ms=elapsed_ms,
                        fail_count=0,
                    )
                )
                await db.commit()

            logger.info("Proxy %s:%d alive (%dms)", proxy.host, proxy.port, elapsed_ms)
            return True

        except Exception as exc:
            async with async_session_factory() as db:
                result = await db.execute(select(Proxy).where(Proxy.id == proxy.id))
                p = result.scalar_one_or_none()
                if p:
                    p.fail_count += 1
                    if p.fail_count >= 3:
                        p.is_active = False
                        logger.warning("Proxy %s:%d deactivated after %d failures", proxy.host, proxy.port, p.fail_count)
                    await db.commit()

            logger.warning("Proxy %s:%d check failed: %s", proxy.host, proxy.port, exc)
            return False

    @staticmethod
    async def check_all_proxies() -> str:
        """Check all proxies. Returns summary."""
        async with async_session_factory() as db:
            result = await db.execute(select(Proxy))
            proxies = list(result.scalars().all())

        if not proxies:
            return "No proxies configured"

        alive = 0
        for proxy in proxies:
            if await ProxyManager.check_proxy(proxy):
                alive += 1

        return f"{alive}/{len(proxies)} proxies healthy"

    @staticmethod
    async def get_active_proxy() -> Proxy | None:
        """Get the fastest active proxy."""
        async with async_session_factory() as db:
            result = await db.execute(
                select(Proxy)
                .where(Proxy.is_active.is_(True))
                .order_by(Proxy.response_time_ms.asc().nullslast())
            )
            return result.scalar_one_or_none()
