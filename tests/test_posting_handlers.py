"""
Тесты для posting Kafka handlers — send, edit, delete — стиль Димы.
Хендлеры создаются через create_posting_handlers factory.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.modules.posting.handlers import create_posting_handlers


# =============================================================================
# Fixtures
# =============================================================================
@pytest.fixture
def mock_posting_service():
    """Фикстура для мока PostingService."""
    service = MagicMock()
    service.send_message = AsyncMock(return_value={"message_id": 123, "chat_id": "-1001234567890"})
    service.edit_message = AsyncMock(return_value={"message_id": 123, "chat_id": "-1001234567890"})
    service.delete_message = AsyncMock(return_value=None)
    return service


@pytest.fixture
def mock_producer():
    """Фикстура для мока KafkaResultProducer."""
    producer = MagicMock()
    producer.send_result = AsyncMock()
    return producer


@pytest.fixture
def handlers(mock_posting_service):
    """Фикстура для создания хендлеров."""
    return create_posting_handlers(mock_posting_service)


@pytest.fixture
def send_request():
    """Пример запроса на отправку сообщения."""
    return MagicMock(
        request_id="send-001",
        callback_task_name="tasks.posting:on_post_published",
        result_topic="tad_send_bot_message_result",
        payload={
            "platform": {
                "internal_id": "-1001234567890",
            },
            "message": {
                "text": "Test message",
                "parse_mode": "HTML",
            },
        },
    )


@pytest.fixture
def edit_request():
    """Пример запроса на редактирование сообщения."""
    return MagicMock(
        request_id="edit-001",
        callback_task_name="tasks.posting:on_post_published",
        result_topic="tad_edit_bot_message_result",
        payload={
            "platform": {
                "internal_id": "-1001234567890",
            },
            "message": {
                "message_id": 42,
                "text": "Updated text",
            },
        },
    )


@pytest.fixture
def delete_request():
    """Пример запроса на удаление сообщения."""
    return MagicMock(
        request_id="delete-001",
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


@pytest.fixture
def patch_idempotency():
    """Фикстура для патча idempotency check."""
    with patch("src.modules.posting.handlers._check_idempotency", new_callable=AsyncMock) as mock:
        mock.return_value = False
        yield mock


# =============================================================================
# Send Message Tests
# =============================================================================
@pytest.mark.asyncio
async def test_send_success(handlers, mock_producer, send_request, patch_idempotency):
    """Успешная отправка должна отправлять результат."""
    await handlers["send_bot_message"](send_request, mock_producer)
    
    mock_producer.send_result.assert_awaited_once()
    call_kwargs = mock_producer.send_result.call_args.kwargs
    assert call_kwargs["request"].request_id == "send-001"
    assert call_kwargs["original_topic"] == "send_bot_message"


@pytest.mark.asyncio
async def test_send_duplicate_skips(handlers, mock_producer, send_request, patch_idempotency):
    """Дубликат запроса должен пропускаться."""
    patch_idempotency.return_value = True
    
    await handlers["send_bot_message"](send_request, mock_producer)
    
    mock_producer.send_result.assert_not_awaited()


# =============================================================================
# Edit Message Tests
# =============================================================================
@pytest.mark.asyncio
async def test_edit_success(handlers, mock_producer, edit_request, patch_idempotency):
    """Успешное редактирование должно отправлять результат."""
    await handlers["edit_bot_message"](edit_request, mock_producer)
    
    mock_producer.send_result.assert_awaited_once()
    call_kwargs = mock_producer.send_result.call_args.kwargs
    assert call_kwargs["original_topic"] == "edit_bot_message"


# =============================================================================
# Delete Message Tests
# =============================================================================
@pytest.mark.asyncio
async def test_delete_success(handlers, mock_producer, delete_request, patch_idempotency):
    """Успешное удаление должно отправлять результат."""
    await handlers["delete_bot_message"](delete_request, mock_producer)
    
    mock_producer.send_result.assert_awaited_once()
    call_kwargs = mock_producer.send_result.call_args.kwargs
    assert call_kwargs["original_topic"] == "delete_bot_message"


# =============================================================================
# Handler Keys Tests
# =============================================================================
def test_handlers_returns_expected_keys(mock_posting_service):
    """create_posting_handlers должен возвращать ожидаемые ключи."""
    handlers = create_posting_handlers(mock_posting_service)
    
    assert "send_bot_message" in handlers
    assert "edit_bot_message" in handlers
    assert "delete_bot_message" in handlers
