"""
Тесты для SessionPool — busy-трекинг, release, mark_flood_wait, mark_session_failed — стиль Димы.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.modules.scraping.session_pool import SessionPool


# =============================================================================
# Fixtures
# =============================================================================
@pytest.fixture
def session_pool():
    """Фикстура для SessionPool."""
    return SessionPool(max_size=5)


@pytest.fixture
def mock_session_record():
    """Создать мок записи сессии."""
    def _make(session_id="sess-1", phone="+1234", proxy_id=None,
              fail_count=0, status="active"):
        s = MagicMock()
        s.id = session_id
        s.phone = phone
        s.proxy_id = proxy_id
        s.fail_count = fail_count
        s.status = status
        s.role = "scrape"
        s.flood_wait_until = None
        return s
    return _make


@pytest.fixture
def mock_telethon_client():
    """Создать мок Telethon клиента."""
    def _make(connected=True):
        client = MagicMock()
        client.is_connected.return_value = connected
        client.disconnect = AsyncMock()
        return client
    return _make


@pytest.fixture
def mock_db_factory():
    """Фикстура для мока DB factory."""
    mock_session = AsyncMock()
    mock_factory = MagicMock()
    mock_factory.__aenter__ = AsyncMock(return_value=mock_session)
    mock_factory.__aexit__ = AsyncMock(return_value=False)
    return mock_session, mock_factory


# =============================================================================
# Busy Tracking Tests
# =============================================================================
@pytest.mark.asyncio
async def test_get_session_marks_busy(session_pool, mock_session_record, mock_telethon_client, mock_db_factory):
    """get_session должен помечать сессию как busy."""
    mock_session, mock_factory = mock_db_factory
    
    session = mock_session_record("sess-1")
    client = mock_telethon_client()
    session_pool._pool["sess-1"] = client
    
    with patch("src.modules.scraping.session_pool.async_session_factory", return_value=mock_factory), \
         patch("src.modules.scraping.session_pool.asyncio.sleep", new_callable=AsyncMock):
        
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [session]
        mock_session.execute = AsyncMock(return_value=mock_result)
        
        _, returned_session = await session_pool.get_session(role="scrape")
        
        assert returned_session.id in session_pool._busy


@pytest.mark.asyncio
async def test_release_session_removes_from_busy(session_pool):
    """release_session должен удалять из busy set."""
    session_pool._busy.add("sess-1")
    
    await session_pool.release_session("sess-1")
    
    assert "sess-1" not in session_pool._busy


@pytest.mark.asyncio
async def test_release_nonexistent_session_is_noop(session_pool):
    """release_session для несуществующей сессии не должен падать."""
    # Should not raise
    await session_pool.release_session("nonexistent")


@pytest.mark.asyncio
async def test_concurrent_get_session_prefers_non_busy(session_pool, mock_session_record, mock_telethon_client, mock_db_factory):
    """При занятости одной сессии должна выбираться свободная."""
    mock_session, mock_factory = mock_db_factory
    
    sess1 = mock_session_record("sess-1", "+1111")
    sess2 = mock_session_record("sess-2", "+2222")
    client1 = mock_telethon_client()
    client2 = mock_telethon_client()
    session_pool._pool["sess-1"] = client1
    session_pool._pool["sess-2"] = client2
    
    # Mark sess-1 as busy
    session_pool._busy.add("sess-1")
    
    with patch("src.modules.scraping.session_pool.async_session_factory", return_value=mock_factory), \
         patch("src.modules.scraping.session_pool.asyncio.sleep", new_callable=AsyncMock):
        
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [sess1, sess2]
        mock_session.execute = AsyncMock(return_value=mock_result)
        
        _, returned_session = await session_pool.get_session(role="scrape")
        
        # Should get sess-2 (non-busy)
        assert returned_session.id == "sess-2"
        assert "sess-2" in session_pool._busy


# =============================================================================
# Flood Wait Tests
# =============================================================================
@pytest.mark.asyncio
async def test_flood_wait_removes_from_pool_and_busy(session_pool, mock_telethon_client, mock_db_factory):
    """mark_flood_wait должен удалять сессию из пула и busy set."""
    mock_session, mock_factory = mock_db_factory
    
    session_pool._pool["sess-1"] = mock_telethon_client()
    session_pool._busy.add("sess-1")
    
    with patch("src.modules.scraping.session_pool.async_session_factory", return_value=mock_factory):
        mock_session.execute = AsyncMock()
        mock_session.commit = AsyncMock()
        
        await session_pool.mark_flood_wait("sess-1", 60)
        
        assert "sess-1" not in session_pool._pool
        assert "sess-1" not in session_pool._busy


# =============================================================================
# Mark Session Failed Tests
# =============================================================================
@pytest.mark.asyncio
async def test_fail_count_incremented(session_pool, mock_session_record, mock_db_factory):
    """mark_session_failed должен инкрементировать fail_count."""
    mock_session, mock_factory = mock_db_factory
    
    session = mock_session_record("sess-1", fail_count=0)
    
    with patch("src.modules.scraping.session_pool.async_session_factory", return_value=mock_factory):
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = session
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.commit = AsyncMock()
        
        await session_pool.mark_session_failed("sess-1")
        
        assert session.fail_count == 1
        mock_session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_session_banned_after_5_failures(session_pool, mock_session_record, mock_telethon_client, mock_db_factory):
    """После 5 фейлов сессия должна быть забанена и удалена."""
    mock_session, mock_factory = mock_db_factory
    
    session_pool._pool["sess-1"] = mock_telethon_client()
    session_pool._busy.add("sess-1")
    
    session = mock_session_record("sess-1", fail_count=4)
    
    with patch("src.modules.scraping.session_pool.async_session_factory", return_value=mock_factory):
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = session
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.commit = AsyncMock()
        
        await session_pool.mark_session_failed("sess-1")
        
        assert session.fail_count == 5
        assert session.status == "banned"
        assert "sess-1" not in session_pool._pool
        assert "sess-1" not in session_pool._busy


# =============================================================================
# Close All Tests
# =============================================================================
@pytest.mark.asyncio
async def test_close_all_disconnects(session_pool, mock_telethon_client):
    """close_all должен дисконнектить всех клиентов и очищать пул."""
    client1 = mock_telethon_client()
    client2 = mock_telethon_client()
    session_pool._pool["sess-1"] = client1
    session_pool._pool["sess-2"] = client2
    
    await session_pool.close_all()
    
    assert len(session_pool._pool) == 0
    client1.disconnect.assert_awaited_once()
    client2.disconnect.assert_awaited_once()


@pytest.mark.asyncio
async def test_close_all_handles_errors(session_pool, mock_telethon_client):
    """close_all не должен падать при ошибках дисконнекта."""
    client = mock_telethon_client()
    client.disconnect = AsyncMock(side_effect=RuntimeError("dc failed"))
    session_pool._pool["sess-1"] = client
    
    # Should not raise
    await session_pool.close_all()
    assert len(session_pool._pool) == 0
