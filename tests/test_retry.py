"""
Tests for retry with exponential backoff.
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from src.modules.posting.retry import send_with_retry, MAX_RETRIES, BACKOFF_SECONDS
from src.core.exceptions import BotError, NoAvailableBotError
from src.core import error_codes


@pytest.fixture
def mock_bot_pool():
    pool = AsyncMock()
    bot = AsyncMock()
    account = MagicMock()
    account.id = "bot-001"
    pool.get_bot_for_platform = AsyncMock(return_value=(bot, account))
    pool.mark_bot_failed = AsyncMock()
    return pool, bot, account


class TestSendWithRetry:
    @pytest.mark.asyncio
    async def test_success_first_try(self, mock_bot_pool):
        pool, bot, account = mock_bot_pool
        msg = MagicMock()
        msg.message_id = 42
        bot.send_message = AsyncMock(return_value=msg)

        result = await send_with_retry(
            bot_pool=pool,
            platform_id="platform-001",
            operation="send_message",
            kwargs={"chat_id": "-100123", "text": "test"},
        )
        assert result["message_id"] == 42

    @pytest.mark.asyncio
    @patch("src.modules.posting.retry.asyncio.sleep", new_callable=AsyncMock)
    async def test_retry_on_failure(self, mock_sleep, mock_bot_pool):
        pool, bot, account = mock_bot_pool
        msg = MagicMock()
        msg.message_id = 42

        bot.send_message = AsyncMock(
            side_effect=[
                BotError("fail1", error_code="BOT_BLOCKED"),
                BotError("fail2", error_code="BOT_BLOCKED"),
                msg,  # success on 3rd try
            ]
        )

        result = await send_with_retry(
            bot_pool=pool,
            platform_id="platform-001",
            operation="send_message",
            kwargs={"chat_id": "-100123", "text": "test"},
        )
        assert result["message_id"] == 42
        assert mock_sleep.call_count == 2
        # Verify exponential backoff: 1s, 2s
        mock_sleep.assert_any_call(1)
        mock_sleep.assert_any_call(2)

    @pytest.mark.asyncio
    @patch("src.modules.posting.retry.asyncio.sleep", new_callable=AsyncMock)
    async def test_all_retries_exhausted(self, mock_sleep, mock_bot_pool):
        pool, bot, account = mock_bot_pool
        bot.send_message = AsyncMock(
            side_effect=BotError("always fail", error_code="BOT_BLOCKED")
        )

        with pytest.raises(BotError) as exc_info:
            await send_with_retry(
                bot_pool=pool,
                platform_id="platform-001",
                operation="send_message",
                kwargs={"chat_id": "-100123", "text": "test"},
            )
        assert exc_info.value.error_code == error_codes.ALL_BOTS_FAILED

    @pytest.mark.asyncio
    async def test_no_retry_on_rate_limit(self, mock_bot_pool):
        pool, bot, account = mock_bot_pool
        bot.send_message = AsyncMock(
            side_effect=BotError("rate limited", error_code=error_codes.BOT_RATE_LIMITED)
        )

        with pytest.raises(BotError) as exc_info:
            await send_with_retry(
                bot_pool=pool,
                platform_id="platform-001",
                operation="send_message",
                kwargs={"chat_id": "-100123", "text": "test"},
            )
        assert exc_info.value.error_code == error_codes.BOT_RATE_LIMITED
        pool.mark_bot_failed.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_retry_on_no_bots(self, mock_bot_pool):
        pool, bot, account = mock_bot_pool
        pool.get_bot_for_platform = AsyncMock(side_effect=NoAvailableBotError())

        with pytest.raises(NoAvailableBotError):
            await send_with_retry(
                bot_pool=pool,
                platform_id="platform-001",
                operation="send_message",
                kwargs={"chat_id": "-100123", "text": "test"},
            )


class TestBackoffConstants:
    def test_backoff_values(self):
        assert BACKOFF_SECONDS == [1, 2, 4]

    def test_max_retries(self):
        assert MAX_RETRIES == 3
