"""
Общие фикстуры для тестов
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from src.transport.schemas import TaskRequestSchema
from src.modules.posting.bot_pool import BotPool
from src.modules.scraping.session_pool import SessionPool


@pytest.fixture
def mock_producer():
    """Мок KafkaResultProducer."""
    producer = AsyncMock()
    producer.send_result = AsyncMock()
    return producer


@pytest.fixture
def bot_pool():
    """BotPool фикстура для тестов."""
    return BotPool(max_size=5)


@pytest.fixture
def session_pool():
    """SessionPool фикстура для тестов."""
    return SessionPool(max_size=5)


@pytest.fixture
def mock_bot():
    """Создать мок бота с сессией."""
    bot = MagicMock()
    bot.session = MagicMock()
    bot.session.close = AsyncMock()
    return bot


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
def encryption_key():
    """Генерация тестового ключа шифрования."""
    return Fernet.generate_key().decode()


@pytest.fixture
def sample_scrape_request():
    """Пример scrape_platform TaskRequestSchema."""
    return TaskRequestSchema(
        request_id="test-scrape-001",
        callback_task_name="tasks.parsing:save_parsing_results",
        result_topic="tad_scrape_platform_result",
        payload={
            "platform": {
                "id": "550e8400-e29b-41d4-a716-446655440000",
                "url": "https://t.me/test_channel",
            }
        },
    )


@pytest.fixture
def sample_send_request():
    """Пример send_bot_message TaskRequestSchema."""
    return TaskRequestSchema(
        request_id="test-send-001",
        callback_task_name="tasks.posting:on_post_published",
        result_topic="tad_send_bot_message_result",
        payload={
            "platform": {
                "id": "550e8400-e29b-41d4-a716-446655440000",
                "url": "https://t.me/test_channel",
                "internal_id": "-1001234567890",
            },
            "message": {
                "text": "Test ad message\n\n#ad",
                "parse_mode": "HTML",
            },
        },
    )


@pytest.fixture
def sample_edit_request():
    """Пример edit_bot_message TaskRequestSchema."""
    return TaskRequestSchema(
        request_id="test-edit-001",
        callback_task_name="tasks.posting:on_post_published",
        result_topic="tad_edit_bot_message_result",
        payload={
            "platform": {
                "id": "550e8400-e29b-41d4-a716-446655440000",
                "internal_id": "-1001234567890",
            },
            "message": {
                "message_id": 42,
                "text": "Updated ad message\n\n#ad",
                "parse_mode": "HTML",
            },
        },
    )


@pytest.fixture
def sample_delete_request():
    """Пример delete_bot_message TaskRequestSchema."""
    return TaskRequestSchema(
        request_id="test-delete-001",
        callback_task_name=None,
        result_topic="tad_delete_bot_message_result",
        payload={
            "platform": {
                "internal_id": "-1001234567890",
            },
            "message": {
                "message_id": 42,
            },
        },
    )
