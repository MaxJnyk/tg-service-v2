"""
Tests for TopicRouter — dispatch logic.
"""

import pytest
from unittest.mock import AsyncMock

from src.transport.router import TopicRouter
from src.transport.schemas import TaskRequestSchema


@pytest.fixture
def router():
    return TopicRouter()


@pytest.fixture
def mock_producer():
    producer = AsyncMock()
    producer.send_result = AsyncMock()
    return producer


class TestTopicRouter:
    @pytest.mark.asyncio
    async def test_register_and_dispatch(self, router, mock_producer):
        handler = AsyncMock()
        router.register("send_bot_message", handler)

        request = TaskRequestSchema(request_id="test-001")
        await router.dispatch("send_bot_message", request, mock_producer)

        handler.assert_called_once_with(request, mock_producer)

    @pytest.mark.asyncio
    async def test_no_handler_sends_error(self, router, mock_producer):
        request = TaskRequestSchema(request_id="test-002")
        await router.dispatch("unknown_topic", request, mock_producer)

        mock_producer.send_result.assert_called_once()
        call_kwargs = mock_producer.send_result.call_args.kwargs
        assert "NO_HANDLER" in call_kwargs["error"]

    @pytest.mark.asyncio
    async def test_multiple_handlers(self, router, mock_producer):
        h1 = AsyncMock()
        h2 = AsyncMock()
        router.register("topic_a", h1)
        router.register("topic_b", h2)

        request = TaskRequestSchema(request_id="test-003")
        await router.dispatch("topic_a", request, mock_producer)

        h1.assert_called_once()
        h2.assert_not_called()
