"""
Tests for SessionPool — busy tracking, release, mark_flood_wait, mark_session_failed.
"""

import asyncio
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.modules.scraping.session_pool import SessionPool


def _make_session(session_id: str = "sess-1", phone: str = "+1234", proxy_id: str | None = None,
                  fail_count: int = 0, status: str = "active"):
    s = MagicMock()
    s.id = session_id
    s.phone = phone
    s.proxy_id = proxy_id
    s.fail_count = fail_count
    s.status = status
    s.role = "scrape"
    s.flood_wait_until = None
    return s


def _make_client(connected: bool = True) -> MagicMock:
    client = MagicMock()
    client.is_connected.return_value = connected
    client.disconnect = AsyncMock()
    return client


class TestBusyTracking:
    @pytest.mark.asyncio
    async def test_get_session_marks_busy(self):
        pool = SessionPool(max_size=5)

        session = _make_session("sess-1")
        client = _make_client()
        pool._pool["sess-1"] = client

        with patch("src.modules.scraping.session_pool.async_session_factory") as mock_sf, \
             patch("src.modules.scraping.session_pool.asyncio.sleep", new_callable=AsyncMock):
            mock_db = AsyncMock()
            mock_sf.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_sf.return_value.__aexit__ = AsyncMock(return_value=False)

            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = [session]
            mock_db.execute = AsyncMock(return_value=mock_result)

            _, returned_session = await pool.get_session(role="scrape")

            assert returned_session.id in pool._busy

    @pytest.mark.asyncio
    async def test_release_session_removes_from_busy(self):
        pool = SessionPool(max_size=5)
        pool._busy.add("sess-1")

        await pool.release_session("sess-1")

        assert "sess-1" not in pool._busy

    @pytest.mark.asyncio
    async def test_release_nonexistent_session_is_noop(self):
        pool = SessionPool(max_size=5)
        # Should not raise
        await pool.release_session("nonexistent")

    @pytest.mark.asyncio
    async def test_concurrent_get_session_prefers_non_busy(self):
        """When one session is busy, get_session should prefer the non-busy one."""
        pool = SessionPool(max_size=5)

        sess1 = _make_session("sess-1", "+1111")
        sess2 = _make_session("sess-2", "+2222")
        client1 = _make_client()
        client2 = _make_client()
        pool._pool["sess-1"] = client1
        pool._pool["sess-2"] = client2

        # Mark sess-1 as busy
        pool._busy.add("sess-1")

        with patch("src.modules.scraping.session_pool.async_session_factory") as mock_sf, \
             patch("src.modules.scraping.session_pool.asyncio.sleep", new_callable=AsyncMock):
            mock_db = AsyncMock()
            mock_sf.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_sf.return_value.__aexit__ = AsyncMock(return_value=False)

            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = [sess1, sess2]
            mock_db.execute = AsyncMock(return_value=mock_result)

            _, returned_session = await pool.get_session(role="scrape")

            # Should get sess-2 (non-busy)
            assert returned_session.id == "sess-2"
            assert "sess-2" in pool._busy


class TestMarkFloodWait:
    @pytest.mark.asyncio
    async def test_flood_wait_removes_from_pool_and_busy(self):
        pool = SessionPool(max_size=5)
        pool._pool["sess-1"] = _make_client()
        pool._busy.add("sess-1")

        with patch("src.modules.scraping.session_pool.async_session_factory") as mock_sf:
            mock_db = AsyncMock()
            mock_sf.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_sf.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_db.execute = AsyncMock()
            mock_db.commit = AsyncMock()

            await pool.mark_flood_wait("sess-1", 60)

            assert "sess-1" not in pool._pool
            assert "sess-1" not in pool._busy


class TestMarkSessionFailed:
    @pytest.mark.asyncio
    async def test_fail_count_incremented(self):
        pool = SessionPool(max_size=5)

        session = _make_session("sess-1", fail_count=0)

        with patch("src.modules.scraping.session_pool.async_session_factory") as mock_sf:
            mock_db = AsyncMock()
            mock_sf.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_sf.return_value.__aexit__ = AsyncMock(return_value=False)

            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = session
            mock_db.execute = AsyncMock(return_value=mock_result)
            mock_db.commit = AsyncMock()

            await pool.mark_session_failed("sess-1")

            assert session.fail_count == 1
            mock_db.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_session_banned_after_5_failures(self):
        pool = SessionPool(max_size=5)
        pool._pool["sess-1"] = _make_client()
        pool._busy.add("sess-1")

        session = _make_session("sess-1", fail_count=4)

        with patch("src.modules.scraping.session_pool.async_session_factory") as mock_sf:
            mock_db = AsyncMock()
            mock_sf.return_value.__aenter__ = AsyncMock(return_value=mock_db)
            mock_sf.return_value.__aexit__ = AsyncMock(return_value=False)

            mock_result = MagicMock()
            mock_result.scalar_one_or_none.return_value = session
            mock_db.execute = AsyncMock(return_value=mock_result)
            mock_db.commit = AsyncMock()

            await pool.mark_session_failed("sess-1")

            assert session.fail_count == 5
            assert session.status == "banned"
            assert "sess-1" not in pool._pool
            assert "sess-1" not in pool._busy


class TestCloseAll:
    @pytest.mark.asyncio
    async def test_close_all_disconnects(self):
        pool = SessionPool(max_size=5)
        client1 = _make_client()
        client2 = _make_client()
        pool._pool["sess-1"] = client1
        pool._pool["sess-2"] = client2

        await pool.close_all()

        assert len(pool._pool) == 0
        client1.disconnect.assert_awaited_once()
        client2.disconnect.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_close_all_handles_errors(self):
        pool = SessionPool(max_size=5)
        client = _make_client()
        client.disconnect = AsyncMock(side_effect=RuntimeError("dc failed"))
        pool._pool["sess-1"] = client

        # Should not raise
        await pool.close_all()
        assert len(pool._pool) == 0
