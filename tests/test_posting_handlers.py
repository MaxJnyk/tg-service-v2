"""
Tests for posting Kafka handlers — send, edit, delete.
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from src.modules.posting.handlers import create_posting_handlers
from src.modules.posting.service import PostingService
from src.core.exceptions import BotError


@pytest.fixture
def mock_redis():
    redis = AsyncMock()
    redis.set = AsyncMock(return_value=True)  # NX succeeded = not duplicate
    return redis


@pytest.fixture
def mock_posting_service():
    service = AsyncMock(spec=PostingService)
    service.send_message = AsyncMock(return_value={"message_id": 42, "chat_id": "-100123"})
    service.edit_message = AsyncMock(return_value={"message_id": 42, "chat_id": "-100123"})
    service.delete_message = AsyncMock(return_value={"message_id": 42, "chat_id": "-100123", "deleted": True})
    return service


@pytest.fixture
def handlers(mock_posting_service, mock_redis):
    with patch("src.modules.posting.handlers.get_redis", return_value=mock_redis):
        yield create_posting_handlers(mock_posting_service)


class TestSendBotMessageHandler:
    @pytest.mark.asyncio
    async def test_success(self, handlers, mock_producer, sample_send_request, mock_posting_service):
        handler = handlers["send_bot_message"]
        await handler(sample_send_request, mock_producer)

        mock_posting_service.send_message.assert_called_once()
        mock_producer.send_result.assert_called_once()
        call_kwargs = mock_producer.send_result.call_args.kwargs
        assert call_kwargs["payload"]["message_id"] == 42
        assert call_kwargs.get("error") is None

    @pytest.mark.asyncio
    async def test_bot_error(self, handlers, mock_producer, sample_send_request, mock_posting_service):
        mock_posting_service.send_message.side_effect = BotError("blocked", error_code="BOT_BLOCKED")

        handler = handlers["send_bot_message"]
        await handler(sample_send_request, mock_producer)

        mock_producer.send_result.assert_called_once()
        call_kwargs = mock_producer.send_result.call_args.kwargs
        assert "BOT_BLOCKED" in call_kwargs["error"]


class TestEditBotMessageHandler:
    @pytest.mark.asyncio
    async def test_success(self, handlers, mock_producer, sample_edit_request, mock_posting_service):
        handler = handlers["edit_bot_message"]
        await handler(sample_edit_request, mock_producer)

        mock_posting_service.edit_message.assert_called_once()
        call_kwargs = mock_producer.send_result.call_args.kwargs
        assert call_kwargs.get("error") is None

    @pytest.mark.asyncio
    async def test_missing_message_id(self, handlers, mock_producer):
        from src.transport.schemas import TaskRequestSchema
        request = TaskRequestSchema(
            request_id="test-no-msgid",
            payload={"platform": {"internal_id": "-100123"}, "message": {"text": "hi"}},
        )
        handler = handlers["edit_bot_message"]
        await handler(request, mock_producer)

        call_kwargs = mock_producer.send_result.call_args.kwargs
        assert "INVALID_PAYLOAD" in call_kwargs["error"]


class TestDeleteBotMessageHandler:
    @pytest.mark.asyncio
    async def test_success(self, handlers, mock_producer, sample_delete_request, mock_posting_service):
        handler = handlers["delete_bot_message"]
        await handler(sample_delete_request, mock_producer)

        mock_posting_service.delete_message.assert_called_once()
        call_kwargs = mock_producer.send_result.call_args.kwargs
        assert call_kwargs["payload"]["deleted"] is True

    @pytest.mark.asyncio
    async def test_missing_message_id(self, handlers, mock_producer):
        from src.transport.schemas import TaskRequestSchema
        request = TaskRequestSchema(
            request_id="test-no-msgid-del",
            payload={"platform": {"internal_id": "-100123"}, "message": {}},
        )
        handler = handlers["delete_bot_message"]
        await handler(request, mock_producer)

        call_kwargs = mock_producer.send_result.call_args.kwargs
        assert "INVALID_PAYLOAD" in call_kwargs["error"]
