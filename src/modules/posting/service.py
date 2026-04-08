"""
Posting service — send/edit/delete messages via aiogram bots.
"""

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNotFound,
    TelegramRetryAfter,
)
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, InputMediaPhoto
from sqlalchemy import update

from src.core import error_codes
from src.core.exceptions import BotError
from src.core.metrics import posting_operations
from src.infrastructure.database import async_session_factory
from src.infrastructure.rate_limiter import RateLimiter
from src.modules.accounts.models import BotAccount
from src.modules.posting.bot_pool import BotPool
from src.modules.posting.retry import BACKOFF_SECONDS, MAX_RETRIES

logger = logging.getLogger(__name__)


class PostingService:
    def __init__(self, bot_pool: BotPool, rate_limiter: RateLimiter | None = None) -> None:
        self._bot_pool = bot_pool
        self._rate_limiter = rate_limiter

    @staticmethod
    def resolve_chat_id(raw: str) -> str | int:
        """Convert platform URL or raw value to a chat_id aiogram understands.

        Examples:
            "https://t.me/channel_name" → "@channel_name"
            "@channel_name"             → "@channel_name"
            "-1001234567890"            → -1001234567890
        """
        if isinstance(raw, str):
            raw = raw.strip()
            # https://t.me/channel or http://t.me/channel
            if "t.me/" in raw:
                username = raw.rstrip("/").split("/")[-1]
                return f"@{username}"
            # Already numeric
            if raw.lstrip("-").isdigit():
                return int(raw)
        return raw

    @staticmethod
    def _build_reply_markup(markup_data: list[dict] | None) -> InlineKeyboardMarkup | None:
        """Build InlineKeyboardMarkup from backend payload."""
        if not markup_data:
            return None
        buttons = []
        for btn in markup_data:
            url = btn.get("url")
            text = btn.get("text", "Link")
            if url:
                buttons.append([InlineKeyboardButton(text=text, url=url)])
        return InlineKeyboardMarkup(inline_keyboard=buttons) if buttons else None

    async def send_message(
        self,
        chat_id: str | int,
        text: str,
        platform_id: str | None = None,
        media: str | None = None,
        markup: list[dict] | None = None,
        parse_mode: str | None = None,
    ) -> dict[str, Any]:
        """Send a new message (text or photo) to a Telegram chat."""
        posting_operations.labels(operation="send").inc()
        reply_markup = self._build_reply_markup(markup)

        if self._rate_limiter:
            await self._rate_limiter.acquire(str(chat_id))

        last_exc: Exception | None = None
        for attempt in range(MAX_RETRIES):
            bot, account = await self._bot_pool.get_bot_for_platform(platform_id or "")
            try:
                if media:
                    msg = await bot.send_photo(
                        chat_id=chat_id,
                        photo=media,
                        caption=text or None,
                        reply_markup=reply_markup,
                        parse_mode=parse_mode,
                    )
                else:
                    msg = await bot.send_message(
                        chat_id=chat_id,
                        text=text,
                        reply_markup=reply_markup,
                        parse_mode=parse_mode,
                    )
                await self._mark_used(account.id)
                logger.info("Sent message to %s via bot %s, message_id=%d", chat_id, account.name, msg.message_id)
                return {"message_id": msg.message_id, "chat_id": str(chat_id)}

            except TelegramRetryAfter as exc:
                last_exc = exc
                logger.warning(
                    "Rate limited bot %s, retry after %ds (attempt %d/%d)",
                    account.name, exc.retry_after, attempt + 1, MAX_RETRIES,
                )
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(exc.retry_after)

            except TelegramForbiddenError as exc:
                last_exc = exc
                await self._bot_pool.mark_bot_failed(account.id)
                logger.warning("Bot %s forbidden (attempt %d/%d), retrying with next bot", account.name, attempt + 1, MAX_RETRIES)
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(BACKOFF_SECONDS[attempt])

            except (TelegramNotFound, TelegramBadRequest) as exc:
                msg = str(exc).lower()
                if "chat not found" in msg or "peer_id_invalid" in msg:
                    raise BotError(str(exc), error_code=error_codes.BOT_CHAT_NOT_FOUND) from exc
                if "not enough rights" in msg or "need administrator" in msg:
                    raise BotError(str(exc), error_code=error_codes.BOT_NOT_ADMIN) from exc
                raise BotError(str(exc), error_code=error_codes.INVALID_PAYLOAD) from exc

        raise BotError(
            f"All {MAX_RETRIES} retries failed: {last_exc}",
            error_code=error_codes.ALL_BOTS_FAILED,
        )

    async def edit_message(
        self,
        chat_id: str | int,
        message_id: int,
        text: str,
        platform_id: str | None = None,
        media: str | None = None,
        markup: list[dict] | None = None,
        parse_mode: str | None = None,
    ) -> dict[str, Any]:
        """Edit an existing message."""
        posting_operations.labels(operation="edit").inc()
        reply_markup = self._build_reply_markup(markup)

        if self._rate_limiter:
            await self._rate_limiter.acquire(str(chat_id))

        last_exc: Exception | None = None
        for attempt in range(MAX_RETRIES):
            bot, account = await self._bot_pool.get_bot_for_platform(platform_id or "")
            try:
                if media:
                    await bot.edit_message_media(
                        chat_id=chat_id,
                        message_id=message_id,
                        media=InputMediaPhoto(media=media, caption=text or None),
                        reply_markup=reply_markup,
                    )
                else:
                    await bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=message_id,
                        text=text,
                        reply_markup=reply_markup,
                        parse_mode=parse_mode,
                    )
                await self._mark_used(account.id)
                logger.info("Edited message %d in %s via bot %s", message_id, chat_id, account.name)
                return {"message_id": message_id, "chat_id": str(chat_id)}

            except TelegramRetryAfter as exc:
                last_exc = exc
                logger.warning(
                    "Rate limited bot %s on edit, retry after %ds (attempt %d/%d)",
                    account.name, exc.retry_after, attempt + 1, MAX_RETRIES,
                )
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(exc.retry_after)

            except TelegramForbiddenError as exc:
                last_exc = exc
                await self._bot_pool.mark_bot_failed(account.id)
                logger.warning("Bot %s forbidden on edit (attempt %d/%d)", account.name, attempt + 1, MAX_RETRIES)
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(BACKOFF_SECONDS[attempt])

            except (TelegramBadRequest, TelegramNotFound) as exc:
                msg = str(exc).lower()
                if "chat not found" in msg or "peer_id_invalid" in msg:
                    raise BotError(str(exc), error_code=error_codes.BOT_CHAT_NOT_FOUND) from exc
                if "not enough rights" in msg or "need administrator" in msg:
                    raise BotError(str(exc), error_code=error_codes.BOT_NOT_ADMIN) from exc
                raise BotError(str(exc), error_code=error_codes.INVALID_PAYLOAD) from exc

        raise BotError(
            f"All {MAX_RETRIES} retries failed: {last_exc}",
            error_code=error_codes.ALL_BOTS_FAILED,
        )

    async def delete_message(
        self,
        chat_id: str | int,
        message_id: int,
        platform_id: str | None = None,
    ) -> dict[str, Any]:
        """Delete a message."""
        posting_operations.labels(operation="delete").inc()

        if self._rate_limiter:
            await self._rate_limiter.acquire(str(chat_id))

        last_exc: Exception | None = None
        for attempt in range(MAX_RETRIES):
            bot, account = await self._bot_pool.get_bot_for_platform(platform_id or "")
            try:
                await bot.delete_message(chat_id=chat_id, message_id=message_id)
                await self._mark_used(account.id)
                logger.info("Deleted message %d in %s via bot %s", message_id, chat_id, account.name)
                return {"message_id": message_id, "chat_id": str(chat_id), "deleted": True}

            except TelegramRetryAfter as exc:
                last_exc = exc
                logger.warning(
                    "Rate limited bot %s on delete, retry after %ds (attempt %d/%d)",
                    account.name, exc.retry_after, attempt + 1, MAX_RETRIES,
                )
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(exc.retry_after)

            except TelegramForbiddenError as exc:
                last_exc = exc
                await self._bot_pool.mark_bot_failed(account.id)
                logger.warning("Bot %s forbidden on delete (attempt %d/%d)", account.name, attempt + 1, MAX_RETRIES)
                if attempt < MAX_RETRIES - 1:
                    await asyncio.sleep(BACKOFF_SECONDS[attempt])

            except (TelegramBadRequest, TelegramNotFound) as exc:
                msg = str(exc).lower()
                if "chat not found" in msg or "peer_id_invalid" in msg:
                    raise BotError(str(exc), error_code=error_codes.BOT_CHAT_NOT_FOUND) from exc
                if "not enough rights" in msg or "need administrator" in msg:
                    raise BotError(str(exc), error_code=error_codes.BOT_NOT_ADMIN) from exc
                raise BotError(str(exc), error_code=error_codes.INVALID_PAYLOAD) from exc

        raise BotError(
            f"All {MAX_RETRIES} retries failed: {last_exc}",
            error_code=error_codes.ALL_BOTS_FAILED,
        )

    # Batch _mark_used updates to reduce DB round-trips under load.
    # Accumulated IDs are flushed every _MARK_FLUSH_INTERVAL or when batch is full.
    _mark_pending: set[str] = set()
    _mark_lock: asyncio.Lock = asyncio.Lock()
    _MARK_BATCH_SIZE: int = 20
    _MARK_FLUSH_INTERVAL: float = 5.0  # seconds

    @classmethod
    async def _mark_used(cls, bot_account_id: str) -> None:
        async with cls._mark_lock:
            cls._mark_pending.add(bot_account_id)
            if len(cls._mark_pending) >= cls._MARK_BATCH_SIZE:
                await cls._flush_mark_used()

    @classmethod
    async def _flush_mark_used(cls) -> None:
        """Flush all pending _mark_used updates in a single DB round-trip."""
        if not cls._mark_pending:
            return
        ids = list(cls._mark_pending)
        cls._mark_pending.clear()
        try:
            async with async_session_factory() as session:
                await session.execute(
                    update(BotAccount)
                    .where(BotAccount.id.in_(ids))
                    .values(last_used_at=datetime.now(UTC))
                )
                await session.commit()
        except Exception as exc:
            logger.warning("Failed to batch-update last_used_at for %d bots: %s", len(ids), exc)
