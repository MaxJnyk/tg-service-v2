"""
Сервис парсинга — скрейпит Telegram-каналы через Telethon.

Возвращает данные **точно** в формате tad-backend:
``tasks.parsing:save_parsing_results`` → ``ParsingResultPayload``.

Поля: title, description, item_type, external_id, avatar,
members_count, images/videos/links/reactions/forwards/replies_count,
average_views_count_daily/weekly/monthly,
average_messages_daily/weekly/monthly,
median_views_daily/weekly/monthly,
men_percent, daily_metrics[].
"""

import asyncio
import logging
from collections import defaultdict
from statistics import median
from typing import Any

from telethon.errors import (
    ChannelInvalidError,
    ChannelPrivateError,
    FloodWaitError,
    UsernameInvalidError,
    UsernameNotOccupiedError,
    UserBannedInChannelError,
)
from telethon.tl.functions.channels import GetFullChannelRequest
from telethon.tl.types import ChatFull

from src.config import settings
from src.core import error_codes
from src.core.exceptions import SessionError
from src.core.metrics import scraping_operations
from src.core.security import mask_phone
from src.modules.scraping.session_pool import SessionPool

_TELETHON_TIMEOUT = 60  # таймаут на одну операцию парсинга

logger = logging.getLogger(__name__)

# Глобальный семафор: макс 10 параллельных операций парсинга (защита от FloodWait)
_SCRAPING_SEM = asyncio.Semaphore(10)

_MAX_SCRAPE_RETRIES = 3
_SCRAPE_BACKOFF = [1, 2, 4]


class ScrapingService:
    def __init__(self, session_pool: SessionPool) -> None:
        self._pool = session_pool

    async def scrape_platform(self, username: str, platform_id: str | None = None) -> dict[str, Any]:
        """Спарсить статистику канала — совместимо с tad-backend save_parsing_results.

        До 3 попыток с разными сессиями при FloodWait/ошибке.
        """
        scraping_operations.inc()

        async with _SCRAPING_SEM:
            last_exc: Exception | None = None

            for attempt in range(_MAX_SCRAPE_RETRIES):
                client, session = await self._pool.get_session(role="scrape")
                try:
                    result = await asyncio.wait_for(
                        self._do_scrape(client, session, username),
                        timeout=_TELETHON_TIMEOUT,
                    )
                    await self._pool.mark_used(session.id)
                    await self._pool.release_session(session.id)
                    return result

                except (UsernameNotOccupiedError, UsernameInvalidError, ChannelInvalidError, ValueError) as exc:
                    # Канал не существует или username невалид — сессия в порядке, ретрай не нужен
                    await self._pool.mark_used(session.id)
                    await self._pool.release_session(session.id)
                    raise SessionError(
                        str(exc),
                        error_code=error_codes.SESSION_NOT_AVAILABLE,
                    ) from exc

                except ChannelPrivateError as exc:
                    # Приватный канал — сессия в порядке, ретрай не нужен
                    await self._pool.mark_used(session.id)
                    await self._pool.release_session(session.id)
                    raise SessionError(
                        f"Channel @{username} is private",
                        error_code=error_codes.SESSION_NOT_AVAILABLE,
                    ) from exc

                except FloodWaitError as exc:
                    last_exc = exc
                    logger.warning(
                        "FloodWait %ds on session %s (attempt %d/%d), switching session",
                        exc.seconds, mask_phone(session.phone), attempt + 1, _MAX_SCRAPE_RETRIES,
                    )
                    await self._pool.mark_flood_wait(session.id, exc.seconds)
                    if attempt < _MAX_SCRAPE_RETRIES - 1:
                        await asyncio.sleep(_SCRAPE_BACKOFF[attempt])

                except UserBannedInChannelError as exc:
                    last_exc = exc
                    await self._pool.mark_session_failed(session.id)
                    logger.warning(
                        "Session %s banned (attempt %d/%d), switching session",
                        mask_phone(session.phone), attempt + 1, _MAX_SCRAPE_RETRIES,
                    )
                    if attempt < _MAX_SCRAPE_RETRIES - 1:
                        await asyncio.sleep(_SCRAPE_BACKOFF[attempt])

                except Exception as exc:
                    last_exc = exc
                    exc_str = str(exc)
                    await self._pool.mark_session_failed(session.id)
                    if "frozen" in exc_str.lower() or "ACCOUNT_FROZEN" in exc_str:
                        # Замороженный аккаунт — ретрай бесполезен, сразу ошибка
                        logger.warning("Session %s is frozen, marking as failed", mask_phone(session.phone))
                        raise SessionError(
                            f"Account frozen: {exc}",
                            error_code=error_codes.SESSION_NOT_AVAILABLE,
                        ) from exc
                    logger.warning(
                        "Session %s error: %s (attempt %d/%d)",
                        mask_phone(session.phone), exc, attempt + 1, _MAX_SCRAPE_RETRIES,
                    )
                    if attempt < _MAX_SCRAPE_RETRIES - 1:
                        await asyncio.sleep(_SCRAPE_BACKOFF[attempt])

            # Все попытки исчерпаны
            if isinstance(last_exc, FloodWaitError):
                raise SessionError(
                    f"FloodWait after {_MAX_SCRAPE_RETRIES} retries",
                    error_code=error_codes.SESSION_FLOOD_WAIT,
                ) from last_exc
            if isinstance(last_exc, UserBannedInChannelError):
                raise SessionError(
                    str(last_exc),
                    error_code=error_codes.SESSION_BANNED,
                ) from last_exc
            raise SessionError(
                f"All {_MAX_SCRAPE_RETRIES} scrape retries failed: {last_exc}",
                error_code=error_codes.SESSION_NOT_AVAILABLE,
            ) from last_exc

    async def _do_scrape(self, client: Any, session: Any, username: str) -> dict[str, Any]:
        """Выполнить одну попытку парсинга."""
        entity = await client.get_entity(username)

        full: ChatFull = await client(GetFullChannelRequest(entity))
        full_chat = full.full_chat
        chat = full.chats[0]

        common_data = {
            "title": getattr(chat, "title", ""),
            "description": getattr(full_chat, "about", "") or "",
            "item_type": "CHANNEL" if getattr(chat, "broadcast", False) else "GROUP",
            "external_id": chat.id,
            "avatar": None,
            "members_count": getattr(full_chat, "participants_count", 0) or 0,
        }

        stat_data = await self._collect_stat_info(client, chat)
        result = {**common_data, **stat_data}

        logger.info(
            "Scraped %s: %d members, avg_views_daily=%d, %d daily_metrics",
            username,
            common_data["members_count"],
            stat_data.get("average_views_count_daily", 0),
            len(stat_data.get("daily_metrics", [])),
        )
        return result

    @staticmethod
    async def _collect_stat_info(client: Any, chat: Any) -> dict[str, Any]:
        """Пройтись по сообщениям канала и посчитать статистику для ParsingResultPayload."""
        images_count = 0
        videos_count = 0
        links_count = 0
        reactions_count = 0
        forwards_count = 0
        replies_count = 0

        daily_views: dict[str, dict] = defaultdict(
            lambda: {"total_views": 0, "count": 0, "reactions": 0, "comments": 0, "forwards": 0}
        )
        weekly_views: dict[str, dict] = defaultdict(lambda: {"total_views": 0, "count": 0})
        monthly_views: dict[str, dict] = defaultdict(lambda: {"total_views": 0, "count": 0})

        messages_count = 0
        async for msg in client.iter_messages(chat, limit=settings.MAX_MSG_ANALYZE):
            if not msg.date:
                continue
            messages_count += 1
            d = msg.date.date()
            range_day = f"{d.year}-{d.month:02d}-{d.day:02d}"
            range_week = f"{d.year}-{d.isocalendar()[1]:02d}"
            range_month = f"{d.year}-{d.month:02d}"

            daily_views[range_day]["count"] += 1
            if msg.views:
                daily_views[range_day]["total_views"] += msg.views
                weekly_views[range_week]["total_views"] += msg.views
                weekly_views[range_week]["count"] += 1
                monthly_views[range_month]["total_views"] += msg.views
                monthly_views[range_month]["count"] += 1

            msg_replies = (msg.to_dict().get("replies") or {}).get("replies") or 0
            replies_count += msg_replies
            msg_forwards = msg.forwards or 0
            forwards_count += msg_forwards
            daily_views[range_day]["comments"] += msg_replies
            daily_views[range_day]["forwards"] += msg_forwards

            if media := msg.media:
                media_dict = media.to_dict()
                if media_dict.get("_") == "MessageMediaPhoto":
                    images_count += 1
                elif (
                    media_dict.get("_") == "MessageMediaDocument"
                    and media_dict.get("document", {}).get("mime_type", "").startswith("video")
                ):
                    videos_count += 1

            if entities := msg.entities:
                links_count += sum(1 for e in entities if "url" in e.to_dict())

            if msg.reactions:
                msg_reactions = sum(r.count for r in msg.reactions.results)
                reactions_count += msg_reactions
                daily_views[range_day]["reactions"] += msg_reactions

        # --- Средние ---
        avg_daily_views = (
            sum(d["total_views"] for d in daily_views.values()) // len(daily_views) if daily_views else 0
        )
        avg_weekly_views = (
            sum(w["total_views"] for w in weekly_views.values()) // len(weekly_views) if weekly_views else 0
        )
        avg_monthly_views = (
            sum(m["total_views"] for m in monthly_views.values()) // len(monthly_views) if monthly_views else 0
        )

        # --- Медианы ---
        median_daily = int(median(d["total_views"] for d in daily_views.values())) if daily_views else 0
        median_weekly = int(median(w["total_views"] for w in weekly_views.values())) if weekly_views else 0
        median_monthly = int(median(m["total_views"] for m in monthly_views.values())) if monthly_views else 0

        # --- Среднее кол-во сообщений ---
        avg_messages_daily = messages_count // len(daily_views) if daily_views else 0
        avg_messages_weekly = messages_count // len(weekly_views) if weekly_views else 0
        avg_messages_monthly = messages_count // len(monthly_views) if monthly_views else 0

        return {
            "average_views_count_daily": avg_daily_views,
            "average_views_count_weekly": avg_weekly_views,
            "average_views_count_monthly": avg_monthly_views,
            "average_messages_daily": avg_messages_daily,
            "average_messages_weekly": avg_messages_weekly,
            "average_messages_monthly": avg_messages_monthly,
            "median_views_daily": median_daily,
            "median_views_weekly": median_weekly,
            "median_views_monthly": median_monthly,
            "images_count": images_count,
            "videos_count": videos_count,
            "links_count": links_count,
            "reactions_count": reactions_count,
            "forwards_count": forwards_count,
            "replies_count": replies_count,
            "men_percent": None,
            "daily_metrics": [
                {
                    "date": day_key,
                    "views_count": day_data["total_views"],
                    "comments_count": day_data["comments"],
                    "reactions_count": day_data["reactions"],
                    "reposts_count": day_data["forwards"],
                    "posts_count": day_data["count"],
                }
                for day_key, day_data in sorted(daily_views.items())
            ],
        }
