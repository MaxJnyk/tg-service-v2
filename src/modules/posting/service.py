"""
Posting service — send/edit/delete messages via aiogram bots.
"""

import logging
from datetime import UTC, datetime
from typing import Any

from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNotFound,
    TelegramRetryAfter,
)
from sqlalchemy import update

from src.core import error_codes
from src.core.exceptions import BotError
from src.core.metrics import posting_operations
from src.infrastructure.database import async_session_factory
from src.modules.accounts.models import BotAccount
from src.modules.posting.bot_pool import BotPool

logger = logging.getLogger(__name__)


class PostingService:
    def __init__(self, bot_pool: BotPool) -> None:
        self._bot_pool = bot_pool

    async def send_message(
        self,
        chat_id: str | int,
        text: str,
        platform_id: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Send a new message to a Telegram chat."""
        posting_operations.labels(operation="send").inc()

        bot, account = await self._bot_pool.get_bot_for_platform(platform_id or "")
        try:
            msg = await bot.send_message(chat_id=chat_id, text=text, **kwargs)
            await self._mark_used(account.id)
            logger.info("Sent message to %s via bot %s, message_id=%d", chat_id, account.name, msg.message_id)
            return {"message_id": msg.message_id, "chat_id": str(chat_id)}

        except TelegramRetryAfter as exc:
            logger.warning("Rate limited bot %s, retry after %ds", account.name, exc.retry_after)
            raise BotError(
                f"Rate limited, retry after {exc.retry_after}s",
                error_code=error_codes.BOT_RATE_LIMITED,
            ) from exc

        except TelegramForbiddenError as exc:
            await self._bot_pool.mark_bot_failed(account.id)
            raise BotError(str(exc), error_code=error_codes.BOT_BLOCKED) from exc

        except TelegramNotFound as exc:
            raise BotError(str(exc), error_code=error_codes.BOT_CHAT_NOT_FOUND) from exc

        except TelegramBadRequest as exc:
            raise BotError(str(exc), error_code=error_codes.BOT_NOT_ADMIN) from exc

    async def edit_message(
        self,
        chat_id: str | int,
        message_id: int,
        text: str,
        platform_id: str | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Edit an existing message."""
        posting_operations.labels(operation="edit").inc()

        bot, account = await self._bot_pool.get_bot_for_platform(platform_id or "")
        try:
            await bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text, **kwargs)
            await self._mark_used(account.id)
            logger.info("Edited message %d in %s via bot %s", message_id, chat_id, account.name)
            return {"message_id": message_id, "chat_id": str(chat_id)}

        except TelegramRetryAfter as exc:
            raise BotError(
                f"Rate limited, retry after {exc.retry_after}s",
                error_code=error_codes.BOT_RATE_LIMITED,
            ) from exc

        except (TelegramForbiddenError, TelegramBadRequest, TelegramNotFound) as exc:
            raise BotError(str(exc), error_code=error_codes.BOT_BLOCKED) from exc

    async def delete_message(
        self,
        chat_id: str | int,
        message_id: int,
        platform_id: str | None = None,
    ) -> dict[str, Any]:
        """Delete a message."""
        posting_operations.labels(operation="delete").inc()

        bot, account = await self._bot_pool.get_bot_for_platform(platform_id or "")
        try:
            await bot.delete_message(chat_id=chat_id, message_id=message_id)
            await self._mark_used(account.id)
            logger.info("Deleted message %d in %s via bot %s", message_id, chat_id, account.name)
            return {"message_id": message_id, "chat_id": str(chat_id), "deleted": True}

        except (TelegramForbiddenError, TelegramBadRequest, TelegramNotFound) as exc:
            raise BotError(str(exc), error_code=error_codes.BOT_BLOCKED) from exc

    @staticmethod
    async def _mark_used(bot_account_id: str) -> None:
        async with async_session_factory() as session:
            await session.execute(
                update(BotAccount)
                .where(BotAccount.id == bot_account_id)
                .values(last_used_at=datetime.now(UTC))
            )
            await session.commit()
