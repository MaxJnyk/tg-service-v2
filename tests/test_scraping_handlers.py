"""
Tests for scraping Kafka handler.
"""

import pytest
from unittest.mock import AsyncMock, patch

from src.modules.scraping.handlers import create_scraping_handlers
from src.modules.scraping.service import ScrapingService
from src.core.exceptions import SessionError


@pytest.fixture
def mock_scraping_service():
    service = AsyncMock(spec=ScrapingService)
    service.scrape_platform = AsyncMock(return_value={
        "platform_id": "550e8400-e29b-41d4-a716-446655440000",
        "title": "Test Channel",
        "username": "test_channel",
        "members_count": 15000,
        "avg_post_reach": 5000,
        "avg_post_forwards": 100,
        "avg_post_reactions": 200,
        "err": 33.33,
        "daily_metrics": [],
        "scraped_at": "2026-04-08T10:00:00+00:00",
    })
    return service


@pytest.fixture
def handlers(mock_scraping_service):
    return create_scraping_handlers(mock_scraping_service)


@pytest.fixture(autouse=True)
def mock_idempotency():
    """Patch idempotency so tests don't need a real Redis."""
    with patch("src.modules.scraping.handlers._check_idempotency", return_value=False):
        yield


class TestScrapePlatformHandler:
    @pytest.mark.asyncio
    async def test_success(self, handlers, mock_producer, sample_scrape_request, mock_scraping_service):
        handler = handlers["scrape_platform"]
        await handler(sample_scrape_request, mock_producer)

        mock_scraping_service.scrape_platform.assert_called_once_with(
            username="test_channel",
            platform_id="550e8400-e29b-41d4-a716-446655440000",
        )
        call_kwargs = mock_producer.send_result.call_args.kwargs
        assert call_kwargs["payload"]["members_count"] == 15000
        assert call_kwargs.get("error") is None

    @pytest.mark.asyncio
    async def test_session_error(self, handlers, mock_producer, sample_scrape_request, mock_scraping_service):
        mock_scraping_service.scrape_platform.side_effect = SessionError(
            "FloodWait 30s", error_code="SESSION_FLOOD_WAIT"
        )

        handler = handlers["scrape_platform"]
        await handler(sample_scrape_request, mock_producer)

        call_kwargs = mock_producer.send_result.call_args.kwargs
        assert "SESSION_FLOOD_WAIT" in call_kwargs["error"]

    @pytest.mark.asyncio
    async def test_duplicate_request_skipped(self, handlers, mock_producer, sample_scrape_request, mock_scraping_service):
        with patch("src.modules.scraping.handlers._check_idempotency", return_value=True):
            handler = handlers["scrape_platform"]
            await handler(sample_scrape_request, mock_producer)

        mock_scraping_service.scrape_platform.assert_not_called()
        mock_producer.send_result.assert_not_called()

    @pytest.mark.asyncio
    async def test_missing_url(self, handlers, mock_producer):
        from src.transport.schemas import TaskRequestSchema
        request = TaskRequestSchema(
            request_id="test-no-url",
            payload={"platform": {"id": "123"}},
        )
        handler = handlers["scrape_platform"]
        await handler(request, mock_producer)

        call_kwargs = mock_producer.send_result.call_args.kwargs
        assert "INVALID_PAYLOAD" in call_kwargs["error"]
