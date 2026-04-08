"""
Tests for PostingService — retry logic, TelegramRetryAfter handling, error classification.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramNotFound,
    TelegramRetryAfter,
)

from src.core.exceptions import BotError
from src.modules.posting.service import PostingService


def _make_bot_pool():
    pool = MagicMock()
    pool.get_bot_for_platform = AsyncMock()
    pool.mark_bot_failed = AsyncMock()
    return pool


def _make_bot_and_account(name: str = "test_bot", account_id: str = "acc-1"):
    bot = MagicMock()
    bot.send_message = AsyncMock()
    bot.send_photo = AsyncMock()
    bot.edit_message_text = AsyncMock()
    bot.edit_message_media = AsyncMock()
    bot.delete_message = AsyncMock()

    account = MagicMock()
    account.id = account_id
    account.name = name
    return bot, account


class TestSendMessage:
    @pytest.mark.asyncio
    @patch("src.modules.posting.service.PostingService._mark_used", new_callable=AsyncMock)
    async def test_success(self, mock_mark_used):
        pool = _make_bot_pool()
        bot, account = _make_bot_and_account()
        pool.get_bot_for_platform.return_value = (bot, account)

        sent_msg = MagicMock()
        sent_msg.message_id = 42
        bot.send_message.return_value = sent_msg

        service = PostingService(pool)
        result = await service.send_message(chat_id="@test", text="hello")

        assert result["message_id"] == 42
        mock_mark_used.assert_awaited_once()

    @pytest.mark.asyncio
    @patch("src.modules.posting.service.PostingService._mark_used", new_callable=AsyncMock)
    @patch("src.modules.posting.service.asyncio.sleep", new_callable=AsyncMock)
    async def test_retry_after_sleeps_and_retries(self, mock_sleep, mock_mark_used):
        """TelegramRetryAfter should sleep for retry_after seconds, then retry."""
        pool = _make_bot_pool()
        bot, account = _make_bot_and_account()
        pool.get_bot_for_platform.return_value = (bot, account)

        # First call: rate limited. Second call: success.
        sent_msg = MagicMock()
        sent_msg.message_id = 99
        exc = TelegramRetryAfter(method=MagicMock(), message="Flood control", retry_after=5)
        bot.send_message.side_effect = [exc, sent_msg]

        service = PostingService(pool)
        result = await service.send_message(chat_id="@test", text="hello")

        assert result["message_id"] == 99
        mock_sleep.assert_awaited_once_with(5)

    @pytest.mark.asyncio
    @patch("src.modules.posting.service.PostingService._mark_used", new_callable=AsyncMock)
    @patch("src.modules.posting.service.asyncio.sleep", new_callable=AsyncMock)
    async def test_forbidden_retries_with_next_bot(self, mock_sleep, mock_mark_used):
        """TelegramForbiddenError should mark bot failed and try next."""
        pool = _make_bot_pool()
        bot1, acc1 = _make_bot_and_account("bot1", "acc-1")
        bot2, acc2 = _make_bot_and_account("bot2", "acc-2")

        pool.get_bot_for_platform.side_effect = [(bot1, acc1), (bot2, acc2)]

        exc = TelegramForbiddenError(method=MagicMock(), message="Forbidden")
        bot1.send_message.side_effect = exc

        sent_msg = MagicMock()
        sent_msg.message_id = 77
        bot2.send_message.return_value = sent_msg

        service = PostingService(pool)
        result = await service.send_message(chat_id="@test", text="hello")

        assert result["message_id"] == 77
        pool.mark_bot_failed.assert_awaited_once_with("acc-1")

    @pytest.mark.asyncio
    @patch("src.modules.posting.service.PostingService._mark_used", new_callable=AsyncMock)
    async def test_chat_not_found_raises_immediately(self, mock_mark_used):
        """Chat not found should raise immediately without retrying."""
        pool = _make_bot_pool()
        bot, account = _make_bot_and_account()
        pool.get_bot_for_platform.return_value = (bot, account)

        exc = TelegramBadRequest(method=MagicMock(), message="Bad Request: chat not found")
        bot.send_message.side_effect = exc

        service = PostingService(pool)
        with pytest.raises(BotError) as exc_info:
            await service.send_message(chat_id="@nonexistent", text="hello")

        assert "BOT_CHAT_NOT_FOUND" in exc_info.value.error_code

    @pytest.mark.asyncio
    @patch("src.modules.posting.service.PostingService._mark_used", new_callable=AsyncMock)
    @patch("src.modules.posting.service.asyncio.sleep", new_callable=AsyncMock)
    async def test_all_retries_exhausted(self, mock_sleep, mock_mark_used):
        """After MAX_RETRIES forbidden errors, should raise ALL_BOTS_FAILED."""
        pool = _make_bot_pool()
        bot, account = _make_bot_and_account()
        pool.get_bot_for_platform.return_value = (bot, account)

        exc = TelegramForbiddenError(method=MagicMock(), message="Forbidden")
        bot.send_message.side_effect = exc

        service = PostingService(pool)
        with pytest.raises(BotError) as exc_info:
            await service.send_message(chat_id="@test", text="hello")

        assert "ALL_BOTS_FAILED" in exc_info.value.error_code


class TestDeleteMessage:
    @pytest.mark.asyncio
    @patch("src.modules.posting.service.PostingService._mark_used", new_callable=AsyncMock)
    async def test_success(self, mock_mark_used):
        pool = _make_bot_pool()
        bot, account = _make_bot_and_account()
        pool.get_bot_for_platform.return_value = (bot, account)

        service = PostingService(pool)
        result = await service.delete_message(chat_id="@test", message_id=42)

        assert result["deleted"] is True
        assert result["message_id"] == 42

    @pytest.mark.asyncio
    @patch("src.modules.posting.service.PostingService._mark_used", new_callable=AsyncMock)
    @patch("src.modules.posting.service.asyncio.sleep", new_callable=AsyncMock)
    async def test_retry_after_on_delete(self, mock_sleep, mock_mark_used):
        """TelegramRetryAfter on delete should sleep and retry."""
        pool = _make_bot_pool()
        bot, account = _make_bot_and_account()
        pool.get_bot_for_platform.return_value = (bot, account)

        exc = TelegramRetryAfter(method=MagicMock(), message="Flood control", retry_after=3)
        bot.delete_message.side_effect = [exc, None]

        service = PostingService(pool)
        result = await service.delete_message(chat_id="@test", message_id=42)

        assert result["deleted"] is True
        mock_sleep.assert_awaited_once_with(3)


class TestResolveChatId:
    def test_url_to_username(self):
        assert PostingService.resolve_chat_id("https://t.me/testchannel") == "@testchannel"

    def test_already_at(self):
        assert PostingService.resolve_chat_id("@testchannel") == "@testchannel"

    def test_numeric_positive(self):
        assert PostingService.resolve_chat_id("12345") == 12345

    def test_numeric_negative(self):
        assert PostingService.resolve_chat_id("-1001234567890") == -1001234567890

    def test_url_with_trailing_slash(self):
        assert PostingService.resolve_chat_id("https://t.me/channel/") == "@channel"
