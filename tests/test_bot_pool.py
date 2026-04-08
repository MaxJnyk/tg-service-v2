"""
Tests for BotPool — LRU eviction, platform cache, mark_bot_failed.
"""

from collections import OrderedDict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.modules.posting.bot_pool import BotPool, _PLATFORM_CACHE_TTL


def _make_bot(bot_id: str = "bot-1") -> MagicMock:
    bot = MagicMock()
    bot.session = MagicMock()
    bot.session.close = AsyncMock()
    return bot


def _make_account(account_id: str = "acc-1", name: str = "test_bot", platform_id: str = "plat-1",
                  is_active: bool = True, fail_count: int = 0):
    acc = MagicMock()
    acc.id = account_id
    acc.name = name
    acc.platform_id = platform_id
    acc.is_active = is_active
    acc.fail_count = fail_count
    acc.bot_token = "encrypted_token"
    return acc


class TestLRUEviction:
    @pytest.mark.asyncio
    async def test_pool_evicts_lru_when_full(self):
        pool = BotPool(max_size=2)

        # Pre-fill pool with 2 bots
        bot1 = _make_bot("bot-1")
        bot2 = _make_bot("bot-2")
        pool._pool["id-1"] = bot1
        pool._pool["id-2"] = bot2

        assert len(pool._pool) == 2

        # Add third bot — should evict id-1 (oldest)
        with patch("src.modules.posting.bot_pool.async_session_factory") as mock_sf, \
             patch("src.modules.posting.bot_pool.decrypt", return_value="fake:token"), \
             patch("src.modules.posting.bot_pool.Bot") as MockBot, \
             patch("src.modules.posting.bot_pool.AiohttpSession"), \
             patch("src.modules.posting.bot_pool.aiohttp"):
            mock_session = AsyncMock()
            mock_sf.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_sf.return_value.__aexit__ = AsyncMock(return_value=False)

            account = _make_account("id-3", "new_bot")
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = account
            mock_session.execute = AsyncMock(return_value=mock_result)

            new_bot = MagicMock()
            MockBot.return_value = new_bot

            result = await pool.get_bot("id-3")

            assert result == new_bot
            assert "id-1" not in pool._pool  # evicted
            assert "id-2" in pool._pool
            assert "id-3" in pool._pool
            bot1.session.close.assert_awaited_once()  # closed on eviction

    def test_move_to_end_on_cache_hit(self):
        pool = BotPool(max_size=5)
        bot1 = _make_bot()
        bot2 = _make_bot()
        pool._pool["id-1"] = bot1
        pool._pool["id-2"] = bot2

        # Access id-1 — should move to end
        result = pool._pool.get("id-1")
        pool._pool.move_to_end("id-1")

        keys = list(pool._pool.keys())
        assert keys == ["id-2", "id-1"]


class TestPlatformCache:
    @pytest.mark.asyncio
    async def test_cache_hit_skips_db(self):
        """Cached platform mapping should skip DB query."""
        pool = BotPool(max_size=5)
        account = _make_account("acc-1", "test_bot")
        bot = _make_bot()
        pool._pool["acc-1"] = bot

        import time
        pool._platform_cache["plat-1"] = (account, time.monotonic())

        with patch("src.modules.posting.bot_pool.async_session_factory") as mock_sf:
            result_bot, result_acc = await pool.get_bot_for_platform("plat-1")

            # DB NOT called
            mock_sf.assert_not_called()
            assert result_bot == bot
            assert result_acc == account

    @pytest.mark.asyncio
    async def test_cache_expired_queries_db(self):
        """Expired cache entry should trigger DB query."""
        pool = BotPool(max_size=5)
        account = _make_account("acc-1", "test_bot")

        import time
        # Set cache entry in the past (expired)
        pool._platform_cache["plat-1"] = (account, time.monotonic() - _PLATFORM_CACHE_TTL - 1)

        with patch("src.modules.posting.bot_pool.async_session_factory") as mock_sf, \
             patch.object(pool, "get_bot", new_callable=AsyncMock) as mock_get_bot:
            mock_session = AsyncMock()
            mock_sf.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_sf.return_value.__aexit__ = AsyncMock(return_value=False)

            new_account = _make_account("acc-2", "new_bot")
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = new_account
            mock_session.execute = AsyncMock(return_value=mock_result)

            mock_get_bot.return_value = _make_bot()

            await pool.get_bot_for_platform("plat-1")

            # DB was called
            mock_session.execute.assert_awaited()

    @pytest.mark.asyncio
    async def test_mark_failed_invalidates_cache(self):
        """mark_bot_failed should remove cached entries for that bot."""
        pool = BotPool(max_size=5)
        account = _make_account("acc-1", "test_bot")

        import time
        pool._platform_cache["plat-1"] = (account, time.monotonic())
        pool._platform_cache["plat-2"] = (account, time.monotonic())

        with patch("src.modules.posting.bot_pool.async_session_factory") as mock_sf:
            mock_session = AsyncMock()
            mock_sf.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_sf.return_value.__aexit__ = AsyncMock(return_value=False)

            db_account = _make_account("acc-1", "test_bot", fail_count=0)
            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = db_account
            mock_session.execute = AsyncMock(return_value=mock_result)

            await pool.mark_bot_failed("acc-1")

            assert "plat-1" not in pool._platform_cache
            assert "plat-2" not in pool._platform_cache


class TestCloseAll:
    @pytest.mark.asyncio
    async def test_close_all_clears_pool(self):
        pool = BotPool(max_size=5)
        bot1 = _make_bot()
        bot2 = _make_bot()
        pool._pool["id-1"] = bot1
        pool._pool["id-2"] = bot2

        await pool.close_all()

        assert len(pool._pool) == 0
        bot1.session.close.assert_awaited_once()
        bot2.session.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_close_all_handles_errors(self):
        """close_all should not raise even if a bot.session.close fails."""
        pool = BotPool(max_size=5)
        bot = _make_bot()
        bot.session.close = AsyncMock(side_effect=RuntimeError("close failed"))
        pool._pool["id-1"] = bot

        # Should not raise
        await pool.close_all()
        assert len(pool._pool) == 0
