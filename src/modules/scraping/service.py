"""
Scraping service — scrapes Telegram channels via Telethon.
Returns data in the format expected by tad-backend's save_parsing_results task.
"""

import logging
from datetime import UTC, datetime
from typing import Any

from telethon.errors import FloodWaitError, UserBannedInChannelError
from telethon.tl.functions.channels import GetFullChannelRequest
from telethon.tl.functions.messages import GetHistoryRequest

from src.core import error_codes
from src.core.exceptions import SessionError
from src.core.metrics import scraping_operations
from src.modules.scraping.session_pool import SessionPool

logger = logging.getLogger(__name__)


class ScrapingService:
    def __init__(self, session_pool: SessionPool) -> None:
        self._pool = session_pool

    async def scrape_platform(self, username: str, platform_id: str | None = None) -> dict[str, Any]:
        """Scrape channel stats — compatible with tad-backend save_parsing_results."""
        scraping_operations.inc()

        client, session = await self._pool.get_session(role="scrape")
        try:
            # Resolve channel
            entity = await client.get_entity(username)

            # Full channel info
            full = await client(GetFullChannelRequest(entity))
            full_chat = full.full_chat

            # Recent messages for engagement metrics
            history = await client(GetHistoryRequest(
                peer=entity,
                limit=50,
                offset_date=None,
                offset_id=0,
                max_id=0,
                min_id=0,
                add_offset=0,
                hash=0,
            ))

            # Calculate metrics
            messages = history.messages
            total_views = sum(getattr(m, "views", 0) or 0 for m in messages)
            total_forwards = sum(getattr(m, "forwards", 0) or 0 for m in messages)
            total_reactions = 0
            for m in messages:
                if hasattr(m, "reactions") and m.reactions:
                    total_reactions += sum(r.count for r in m.reactions.results)

            msg_count = len(messages) or 1
            avg_views = total_views // msg_count
            avg_forwards = total_forwards // msg_count
            avg_reactions = total_reactions // msg_count

            # ERR (engagement rate)
            members_count = getattr(full_chat, "participants_count", 0) or 0
            err = round((avg_views / members_count * 100), 2) if members_count > 0 else 0.0

            result = {
                "platform_id": platform_id,
                "title": getattr(entity, "title", ""),
                "username": username,
                "members_count": members_count,
                "avg_post_reach": avg_views,
                "avg_post_forwards": avg_forwards,
                "avg_post_reactions": avg_reactions,
                "err": err,
                "daily_metrics": [],  # Can be extended later
                "scraped_at": datetime.now(UTC).isoformat(),
            }

            await self._pool.mark_used(session.id)
            logger.info(
                "Scraped %s: %d members, avg_views=%d, ERR=%.2f%%",
                username, members_count, avg_views, err,
            )
            return result

        except FloodWaitError as exc:
            logger.warning("FloodWait %ds on session %s", exc.seconds, session.phone)
            await self._pool.mark_flood_wait(session.id, exc.seconds)
            raise SessionError(
                f"FloodWait {exc.seconds}s",
                error_code=error_codes.SESSION_FLOOD_WAIT,
            ) from exc

        except UserBannedInChannelError as exc:
            await self._pool.mark_session_failed(session.id)
            raise SessionError(
                str(exc),
                error_code=error_codes.SESSION_BANNED,
            ) from exc

        except Exception as exc:
            await self._pool.mark_session_failed(session.id)
            raise SessionError(
                str(exc),
                error_code=error_codes.SESSION_NOT_AVAILABLE,
            ) from exc
