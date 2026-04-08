"""
Retry with fallback — exponential backoff (1s, 2s, 4s).

On bot failure:
  1. Mark current bot as failed
  2. Get next bot from pool
  3. Retry with exponential backoff
  4. After max retries → send error result
"""

import asyncio
import logging
from typing import Any

from src.core import error_codes
from src.core.exceptions import BotError, NoAvailableBotError
from src.modules.posting.bot_pool import BotPool

logger = logging.getLogger(__name__)

MAX_RETRIES = 3
BACKOFF_SECONDS = [1, 2, 4]  # exponential backoff


async def send_with_retry(
    bot_pool: BotPool,
    platform_id: str,
    operation: str,
    kwargs: dict[str, Any],
) -> dict[str, Any]:
    """Execute a bot operation with retry and exponential backoff.

    Args:
        bot_pool: BotPool instance
        platform_id: Platform to get bot for
        operation: 'send_message', 'edit_message_text', 'delete_message'
        kwargs: Arguments to pass to the bot method

    Returns:
        Result dict with message_id, chat_id

    Raises:
        BotError: After all retries exhausted
    """
    last_error: Exception | None = None

    for attempt in range(MAX_RETRIES):
        try:
            bot, account = await bot_pool.get_bot_for_platform(platform_id)
            method = getattr(bot, operation)
            result = await method(**kwargs)
            return {
                "message_id": getattr(result, "message_id", None),
                "chat_id": str(kwargs.get("chat_id", "")),
            }

        except NoAvailableBotError:
            raise  # No point retrying if no bots at all

        except BotError as exc:
            last_error = exc
            if exc.error_code == error_codes.BOT_RATE_LIMITED:
                # Don't retry rate limits — caller should handle
                raise

            logger.warning(
                "Bot operation %s failed (attempt %d/%d): %s",
                operation, attempt + 1, MAX_RETRIES, exc,
            )
            await bot_pool.mark_bot_failed(account.id)

            if attempt < MAX_RETRIES - 1:
                backoff = BACKOFF_SECONDS[attempt]
                logger.info("Retrying in %ds (exponential backoff)...", backoff)
                await asyncio.sleep(backoff)

    raise BotError(
        f"All {MAX_RETRIES} retries failed: {last_error}",
        error_code=error_codes.ALL_BOTS_FAILED,
    )
