"""
Тесты для Kafka transport schemas — совместимость с tad-backend — стиль Димы.
"""

import pytest
from uuid import UUID
from pydantic import ValidationError

from src.transport.schemas import (
    PlatformSchema,
    TaskRequestSchema,
    TaskResultSchema,
)


# =============================================================================
# PlatformSchema Tests
# =============================================================================
def test_platform_basic_url():
    """Базовый URL парсится в username."""
    p = PlatformSchema(url="https://t.me/test_channel")
    assert p.username == "test_channel"
    assert p.ausername == "@test_channel"
    assert p.invite_hash is None


def test_platform_invite_link_swap():
    """Если URL — invite-ссылка, она уходит в поле invite_link."""
    p = PlatformSchema(url="https://t.me/+ABC123")
    assert p.url is None
    assert p.invite_link == "https://t.me/+ABC123"
    assert p.invite_hash == "ABC123"


def test_platform_invite_joinchat():
    """Обработка старого формата joinchat."""
    p = PlatformSchema(url="https://t.me/joinchat/XYZ789")
    assert p.url is None
    assert p.invite_hash == "XYZ789"


def test_platform_with_id():
    """Платформа с ID."""
    p = PlatformSchema(
        id="550e8400-e29b-41d4-a716-446655440000",
        url="https://t.me/channel",
    )
    assert str(p.id) == "550e8400-e29b-41d4-a716-446655440000"


def test_platform_empty():
    """Пустая платформа."""
    p = PlatformSchema()
    assert p.username is None
    assert p.invite_hash is None


# =============================================================================
# TaskRequestSchema Tests
# =============================================================================
def test_task_request_parse_from_dict():
    """Парсинг из словаря."""
    data = {
        "request_id": "abc-123",
        "callback_task_name": "tasks.posting:on_post_published",
        "result_topic": "tad_send_bot_message_result",
        "payload": {"platform": {"url": "https://t.me/test"}},
    }
    req = TaskRequestSchema.model_validate(data)
    assert req.request_id == "abc-123"
    assert req.callback_task_name == "tasks.posting:on_post_published"
    assert req.payload["platform"]["url"] == "https://t.me/test"


def test_task_request_minimal():
    """Минимальный запрос — только request_id."""
    req = TaskRequestSchema(request_id="min-001")
    assert req.callback_task_name is None
    assert req.payload is None


def test_task_request_uuid_as_id():
    """UUID как request_id."""
    req = TaskRequestSchema(request_id=UUID("550e8400-e29b-41d4-a716-446655440000"))
    assert str(req.request_id) == "550e8400-e29b-41d4-a716-446655440000"


def test_task_request_rejects_invalid_result_topic():
    """Невалидный result_topic отклоняется."""
    with pytest.raises(ValidationError):
        TaskRequestSchema(
            request_id="test-123",
            result_topic="invalid_topic",
        )


def test_task_request_rejects_system_topic():
    """System topic отклоняется."""
    with pytest.raises(ValidationError):
        TaskRequestSchema(
            request_id="test-123",
            result_topic="__consumer_offsets",
        )


# =============================================================================
# TaskResultSchema Tests
# =============================================================================
def test_task_result_success():
    """Успешный результат."""
    result = TaskResultSchema(
        request_id="abc-123",
        callback_task_name="tasks.posting:on_post_published",
        payload={"message_id": 42, "chat_id": "-1001234567890"},
    )
    assert result.error is None
    assert result.payload["message_id"] == 42


def test_task_result_error():
    """Результат с ошибкой."""
    result = TaskResultSchema(
        request_id="abc-123",
        error="BOT_BLOCKED: bot was blocked by the user",
    )
    assert result.error == "BOT_BLOCKED: bot was blocked by the user"
    assert result.payload is None


def test_task_result_json_serialization():
    """Сериализация в JSON."""
    result = TaskResultSchema(
        request_id="abc-123",
        payload={"message_id": 42},
    )
    data = result.model_dump(mode="json")
    assert isinstance(data, dict)
    assert data["request_id"] == "abc-123"
