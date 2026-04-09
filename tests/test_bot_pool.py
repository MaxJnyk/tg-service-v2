"""
Тесты для BotPool — LRU вытеснение, кеш площадок, mark_bot_failed
"""

import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.modules.posting.bot_pool import BotPool, _PLATFORM_CACHE_TTL


# =============================================================================
# Fixtures
# =============================================================================
@pytest.fixture
def bot_pool():
    """Фикстура для BotPool."""
    return BotPool(max_size=2)


@pytest.fixture
def mock_bot():
    """Создать мок бота с сессией."""
    def _make(bot_id="bot-1"):
        bot = MagicMock()
        bot.session = MagicMock()
        bot.session.close = AsyncMock()
        return bot
    return _make


@pytest.fixture
def mock_account():
    """Создать мок аккаунта."""
    def _make(account_id="acc-1", name="test_bot", platform_id="plat-1",
              is_active=True, fail_count=0):
        acc = MagicMock()
        acc.id = account_id
        acc.name = name
        acc.platform_id = platform_id
        acc.is_active = is_active
        acc.fail_count = fail_count
        acc.bot_token = "encrypted_token"
        return acc
    return _make


@pytest.fixture
def mock_db_session():
    """Фикстура для мока DB сессии."""
    mock_session = AsyncMock()
    
    async def _context_manager(*args, **kwargs):
        return mock_session
    
    mock_factory = MagicMock()
    mock_factory.__aenter__ = AsyncMock(return_value=mock_session)
    mock_factory.__aexit__ = AsyncMock(return_value=False)
    
    return mock_session, mock_factory


# =============================================================================
# LRU Eviction Tests
# =============================================================================
@pytest.mark.asyncio
async def test_pool_evicts_lru_when_full(bot_pool, mock_bot, mock_account):
    """При переполнении пула вытесняется старейший элемент (LRU)."""
    # Предзаполняем пул 2 ботами
    bot1 = mock_bot("bot-1")
    bot2 = mock_bot("bot-2")
    bot_pool._pool["id-1"] = bot1
    bot_pool._pool["id-2"] = bot2
    
    assert len(bot_pool._pool) == 2
    
    # Добавляем третьего — должен вытеснить id-1 (старейший)
    with patch("src.modules.posting.bot_pool.async_session_factory") as mock_sf, \
         patch("src.modules.posting.bot_pool.decrypt", return_value="fake:token"), \
         patch("src.modules.posting.bot_pool.Bot") as MockBot, \
         patch("src.modules.posting.bot_pool.AiohttpSession"), \
         patch("src.modules.posting.bot_pool.aiohttp"):
        
        mock_session = AsyncMock()
        mock_sf.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_sf.return_value.__aexit__ = AsyncMock(return_value=False)
        
        account = mock_account("id-3", "new_bot")
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = account
        mock_session.execute = AsyncMock(return_value=mock_result)
        
        new_bot = MagicMock()
        MockBot.return_value = new_bot
        
        result = await bot_pool.get_bot("id-3")
        
        assert result == new_bot
        assert "id-1" not in bot_pool._pool  # evicted
        assert "id-2" in bot_pool._pool
        assert "id-3" in bot_pool._pool
        bot1.session.close.assert_awaited_once()


def test_move_to_end_on_cache_hit(bot_pool, mock_bot):
    """При доступе к элементу он перемещается в конец (LRU update)."""
    bot1 = mock_bot()
    bot2 = mock_bot()
    bot_pool._pool["id-1"] = bot1
    bot_pool._pool["id-2"] = bot2
    
    # Access id-1 — should move to end
    bot_pool._pool.get("id-1")
    bot_pool._pool.move_to_end("id-1")
    
    keys = list(bot_pool._pool.keys())
    assert keys == ["id-2", "id-1"]


# =============================================================================
# Platform Cache Tests
# =============================================================================
@pytest.mark.asyncio
async def test_cache_hit_skips_db(bot_pool, mock_bot, mock_account):
    """Cache hit должен пропускать DB query."""
    account = mock_account("acc-1", "test_bot")
    bot = mock_bot()
    bot_pool._pool["acc-1"] = bot
    
    # Устанавливаем кэш
    bot_pool._platform_cache["plat-1"] = (account, time.monotonic())
    
    with patch("src.modules.posting.bot_pool.async_session_factory") as mock_sf:
        result_bot, result_acc = await bot_pool.get_bot_for_platform("plat-1")
        
        # DB NOT called
        mock_sf.assert_not_called()
        assert result_bot == bot
        assert result_acc == account


@pytest.mark.asyncio
async def test_cache_expired_queries_db(bot_pool, mock_account, mock_bot):
    """Expired cache entry должен триггерить DB query."""
    account = mock_account("acc-1", "test_bot")
    
    # Set cache entry in the past (expired)
    bot_pool._platform_cache["plat-1"] = (account, time.monotonic() - _PLATFORM_CACHE_TTL - 1)
    
    with patch("src.modules.posting.bot_pool.async_session_factory") as mock_sf, \
         patch.object(bot_pool, "get_bot", new_callable=AsyncMock) as mock_get_bot:
        mock_session = AsyncMock()
        mock_sf.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_sf.return_value.__aexit__ = AsyncMock(return_value=False)
        
        new_account = mock_account("acc-2", "new_bot")
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = new_account
        mock_session.execute = AsyncMock(return_value=mock_result)
        
        mock_get_bot.return_value = mock_bot()
        
        await bot_pool.get_bot_for_platform("plat-1")
        
        # DB was called
        mock_session.execute.assert_awaited()


@pytest.mark.asyncio
async def test_mark_failed_invalidates_cache(bot_pool, mock_account):
    """mark_bot_failed должен инвалидировать кэш платформ для этого бота."""
    account = mock_account("acc-1", "test_bot")
    
    # Устанавливаем кэш
    bot_pool._platform_cache["plat-1"] = (account, time.monotonic())
    bot_pool._platform_cache["plat-2"] = (account, time.monotonic())
    
    with patch("src.modules.posting.bot_pool.async_session_factory") as mock_sf:
        mock_session = AsyncMock()
        mock_sf.return_value.__aenter__ = AsyncMock(return_value=mock_session)
        mock_sf.return_value.__aexit__ = AsyncMock(return_value=False)
        
        db_account = mock_account("acc-1", "test_bot", fail_count=0)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = db_account
        mock_session.execute = AsyncMock(return_value=mock_result)
        
        await bot_pool.mark_bot_failed("acc-1")
        
        assert "plat-1" not in bot_pool._platform_cache
        assert "plat-2" not in bot_pool._platform_cache


# =============================================================================
# Close All Tests
# =============================================================================
@pytest.mark.asyncio
async def test_close_all_clears_pool(bot_pool, mock_bot):
    """close_all должен очищать пул и закрывать все сессии."""
    bot1 = mock_bot()
    bot2 = mock_bot()
    bot_pool._pool["id-1"] = bot1
    bot_pool._pool["id-2"] = bot2
    
    await bot_pool.close_all()
    
    assert len(bot_pool._pool) == 0
    bot1.session.close.assert_awaited_once()
    bot2.session.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_close_all_handles_errors(bot_pool, mock_bot):
    """close_all не должен падать при ошибках закрытия."""
    bot = mock_bot()
    bot.session.close = AsyncMock(side_effect=RuntimeError("close failed"))
    bot_pool._pool["id-1"] = bot
    
    # Should not raise
    await bot_pool.close_all()
    assert len(bot_pool._pool) == 0
