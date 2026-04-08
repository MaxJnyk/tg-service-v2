"""
Tests for scraping service retry logic.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from telethon.errors import FloodWaitError, UserBannedInChannelError

from src.core.exceptions import SessionError
from src.modules.scraping.service import ScrapingService


def _make_mock_pool():
    pool = AsyncMock()
    # Return a new mock client+session on each call (simulates switching sessions)
    pool.get_session = AsyncMock(
        side_effect=lambda role: (AsyncMock(), MagicMock(id="sess-1", phone="+1111"))
    )
    pool.mark_used = AsyncMock()
    pool.mark_flood_wait = AsyncMock()
    pool.mark_session_failed = AsyncMock()
    return pool


class TestScrapingRetry:
    @pytest.mark.asyncio
    async def test_success_first_attempt(self):
        pool = _make_mock_pool()
        service = ScrapingService(pool)

        with patch.object(service, "_do_scrape", new_callable=AsyncMock) as mock_scrape:
            mock_scrape.return_value = {"title": "Test", "members_count": 100}
            result = await service.scrape_platform("test_channel")

        assert result["title"] == "Test"
        assert mock_scrape.call_count == 1
        pool.mark_used.assert_called_once()

    @pytest.mark.asyncio
    async def test_retry_on_flood_wait_then_success(self):
        pool = _make_mock_pool()
        service = ScrapingService(pool)

        flood_exc = FloodWaitError(request=None, capture=0)
        flood_exc.seconds = 30

        with patch.object(service, "_do_scrape", new_callable=AsyncMock) as mock_scrape:
            mock_scrape.side_effect = [
                flood_exc,  # 1st attempt fails
                {"title": "Test", "members_count": 100},  # 2nd succeeds
            ]
            result = await service.scrape_platform("test_channel")

        assert result["title"] == "Test"
        assert mock_scrape.call_count == 2
        pool.mark_flood_wait.assert_called_once()
        pool.mark_used.assert_called_once()

    @pytest.mark.asyncio
    async def test_all_retries_exhausted_flood_wait(self):
        pool = _make_mock_pool()
        service = ScrapingService(pool)

        flood_exc = FloodWaitError(request=None, capture=0)
        flood_exc.seconds = 30

        with patch.object(service, "_do_scrape", new_callable=AsyncMock) as mock_scrape:
            mock_scrape.side_effect = flood_exc
            with pytest.raises(SessionError) as exc_info:
                await service.scrape_platform("test_channel")

        assert exc_info.value.error_code == "SESSION_FLOOD_WAIT"
        assert mock_scrape.call_count == 3
        assert pool.mark_flood_wait.call_count == 3

    @pytest.mark.asyncio
    async def test_retry_on_banned_then_success(self):
        pool = _make_mock_pool()
        service = ScrapingService(pool)

        with patch.object(service, "_do_scrape", new_callable=AsyncMock) as mock_scrape:
            mock_scrape.side_effect = [
                UserBannedInChannelError(request=None),
                {"title": "Test", "members_count": 50},
            ]
            result = await service.scrape_platform("test_channel")

        assert result["members_count"] == 50
        assert mock_scrape.call_count == 2
        pool.mark_session_failed.assert_called_once()

    @pytest.mark.asyncio
    async def test_all_retries_exhausted_generic_error(self):
        pool = _make_mock_pool()
        service = ScrapingService(pool)

        with patch.object(service, "_do_scrape", new_callable=AsyncMock) as mock_scrape:
            mock_scrape.side_effect = ConnectionError("network down")
            with pytest.raises(SessionError) as exc_info:
                await service.scrape_platform("test_channel")

        assert exc_info.value.error_code == "SESSION_NOT_AVAILABLE"
        assert mock_scrape.call_count == 3
        assert pool.mark_session_failed.call_count == 3
