"""
Tests for ScrapingService._collect_stat_info — edge cases: empty messages, median on empty, men_percent.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.modules.scraping.service import ScrapingService
from src.modules.scraping.session_pool import SessionPool


class TestCollectStatInfo:
    @pytest.mark.asyncio
    async def test_empty_messages_returns_zeroes(self):
        """When iter_messages yields nothing, all stats should be zero."""
        pool = MagicMock(spec=SessionPool)
        service = ScrapingService(pool)

        client = MagicMock()
        # iter_messages returns empty async iterator
        async def empty_iter(*args, **kwargs):
            return
            yield  # noqa: unreachable — makes it an async generator

        client.iter_messages = empty_iter

        result = await service._collect_stat_info(client, "testchannel")

        assert result["images_count"] == 0
        assert result["videos_count"] == 0
        assert result["links_count"] == 0
        assert result["reactions_count"] == 0
        assert result["forwards_count"] == 0
        assert result["replies_count"] == 0
        assert result["average_views_count_daily"] == 0
        assert result["median_views_daily"] == 0
        assert result["daily_metrics"] == []

    @pytest.mark.asyncio
    async def test_men_percent_is_none(self):
        """men_percent should be None (no data) not 0."""
        pool = MagicMock(spec=SessionPool)
        service = ScrapingService(pool)

        client = MagicMock()
        async def empty_iter(*args, **kwargs):
            return
            yield

        client.iter_messages = empty_iter

        result = await service._collect_stat_info(client, "testchannel")
        assert result["men_percent"] is None
