"""
Tests for Kafka transport schemas — compatibility with tad-backend.
"""

import pytest
from uuid import UUID

from src.transport.schemas import (
    PlatformSchema,
    PayloadSchema,
    TaskRequestSchema,
    TaskResultSchema,
)


class TestPlatformSchema:
    def test_basic_url(self):
        p = PlatformSchema(url="https://t.me/test_channel")
        assert p.username == "test_channel"
        assert p.ausername == "@test_channel"
        assert p.invite_hash is None

    def test_invite_link_swap(self):
        """If URL is an invite link, it should be swapped to invite_link field."""
        p = PlatformSchema(url="https://t.me/+ABC123")
        assert p.url is None
        assert p.invite_link == "https://t.me/+ABC123"
        assert p.invite_hash == "ABC123"

    def test_invite_joinchat(self):
        p = PlatformSchema(url="https://t.me/joinchat/XYZ789")
        assert p.url is None
        assert p.invite_hash == "XYZ789"

    def test_with_id(self):
        p = PlatformSchema(
            id="550e8400-e29b-41d4-a716-446655440000",
            url="https://t.me/channel",
        )
        assert p.id == "550e8400-e29b-41d4-a716-446655440000"

    def test_empty(self):
        p = PlatformSchema()
        assert p.username is None
        assert p.invite_hash is None


class TestTaskRequestSchema:
    def test_parse_from_dict(self):
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

    def test_minimal(self):
        req = TaskRequestSchema(request_id="min-001")
        assert req.callback_task_name is None
        assert req.payload is None

    def test_uuid_request_id(self):
        req = TaskRequestSchema(request_id=UUID("550e8400-e29b-41d4-a716-446655440000"))
        assert str(req.request_id) == "550e8400-e29b-41d4-a716-446655440000"


class TestTaskResultSchema:
    def test_success_result(self):
        result = TaskResultSchema(
            request_id="abc-123",
            callback_task_name="tasks.posting:on_post_published",
            payload={"message_id": 42, "chat_id": "-1001234567890"},
        )
        assert result.error is None
        assert result.payload["message_id"] == 42

    def test_error_result(self):
        result = TaskResultSchema(
            request_id="abc-123",
            error="BOT_BLOCKED: bot was blocked by the user",
        )
        assert result.error == "BOT_BLOCKED: bot was blocked by the user"
        assert result.payload is None

    def test_json_serialization(self):
        result = TaskResultSchema(
            request_id="abc-123",
            payload={"message_id": 42},
        )
        data = result.model_dump(mode="json")
        assert isinstance(data, dict)
        assert data["request_id"] == "abc-123"
