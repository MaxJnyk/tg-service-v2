"""
Тесты для ScrapingService._collect_stat_info — edge cases: пустые сообщения, медиана на пустоте, men_percent.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.modules.scraping.service import ScrapingService
from src.modules.scraping.session_pool import SessionPool


class TestCollectStatInfo:
    @pytest.mark.asyncio
    async def test_empty_messages_returns_zeroes(self):
        """Когда iter_messages ничего не возвращает, все статистики должны быть нулем."""
        pool = MagicMock(spec=SessionPool)
        service = ScrapingService(pool)

        client = MagicMock()
        # iter_messages возвращает пустой async iterator
        async def empty_iter(*args, **kwargs):
            return
            yield  # noqa: unreachable — делает его async generator

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
        """men_percent должен быть None (нет данных), не 0."""
        pool = MagicMock(spec=SessionPool)
        service = ScrapingService(pool)

        client = MagicMock()
        async def empty_iter(*args, **kwargs):
            return
            yield

        client.iter_messages = empty_iter

        result = await service._collect_stat_info(client, "testchannel")
        assert result["men_percent"] is None
