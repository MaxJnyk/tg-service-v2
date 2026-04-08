"""
Shared test fixtures.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from src.transport.schemas import TaskRequestSchema


@pytest.fixture
def mock_producer():
    """Mock KafkaResultProducer."""
    producer = AsyncMock()
    producer.send_result = AsyncMock()
    return producer


@pytest.fixture
def sample_scrape_request():
    """Sample scrape_platform TaskRequestSchema."""
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
    """Sample send_bot_message TaskRequestSchema."""
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
    """Sample edit_bot_message TaskRequestSchema."""
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
    """Sample delete_bot_message TaskRequestSchema."""
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
