"""
Тесты для Redis-based идемпотентности — стиль Димы (flat functions).
"""

import pytest
from unittest.mock import AsyncMock, patch


@pytest.fixture
def mock_redis():
    """Фикстура для мока Redis."""
    redis = AsyncMock()
    return redis


@pytest.fixture(autouse=True)
def patch_get_redis(mock_redis):
    """Автоматически патчим get_redis для всех тестов."""
    with patch("src.modules.billing.idempotency.get_redis", return_value=mock_redis) as _patch:
        yield _patch


@pytest.mark.asyncio
async def test_first_request_not_duplicate(mock_redis):
    """Первый запрос не дубликат (NX success)."""
    mock_redis.set = AsyncMock(return_value=True)

    from src.modules.billing.idempotency import is_duplicate
    result = await is_duplicate("req-001")
    assert result is False


@pytest.mark.asyncio
async def test_second_request_is_duplicate(mock_redis):
    """Второй запрос — дубликат (NX fail)."""
    mock_redis.set = AsyncMock(return_value=None)

    from src.modules.billing.idempotency import is_duplicate
    result = await is_duplicate("req-001")
    assert result is True


@pytest.mark.asyncio
async def test_clear_idempotency(mock_redis):
    """Очистка ключа идемпотентности."""
    mock_redis.delete = AsyncMock()

    from src.modules.billing.idempotency import clear_idempotency
    await clear_idempotency("req-001")
    mock_redis.delete.assert_called_once_with("idempotency:req-001")
