"""
Tests for Redis-based idempotency guard.
"""

import pytest
from unittest.mock import AsyncMock, patch


class TestIdempotency:
    @pytest.mark.asyncio
    @patch("src.modules.billing.idempotency.get_redis")
    async def test_first_request_not_duplicate(self, mock_get_redis):
        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock(return_value=True)  # NX succeeded = first time
        mock_get_redis.return_value = mock_redis

        from src.modules.billing.idempotency import is_duplicate
        result = await is_duplicate("req-001")
        assert result is False

    @pytest.mark.asyncio
    @patch("src.modules.billing.idempotency.get_redis")
    async def test_second_request_is_duplicate(self, mock_get_redis):
        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock(return_value=None)  # NX failed = already exists
        mock_get_redis.return_value = mock_redis

        from src.modules.billing.idempotency import is_duplicate
        result = await is_duplicate("req-001")
        assert result is True

    @pytest.mark.asyncio
    @patch("src.modules.billing.idempotency.get_redis")
    async def test_clear_idempotency(self, mock_get_redis):
        mock_redis = AsyncMock()
        mock_redis.delete = AsyncMock()
        mock_get_redis.return_value = mock_redis

        from src.modules.billing.idempotency import clear_idempotency
        await clear_idempotency("req-001")
        mock_redis.delete.assert_called_once_with("idempotency:req-001")
