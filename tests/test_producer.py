"""
Тесты для KafkaResultProducer — именование result-топиков и сериализация — стиль Димы.
"""

import re
import pytest

from src.transport.producer import KafkaResultProducer


@pytest.fixture
def producer():
    """Фикстура для KafkaResultProducer."""
    return KafkaResultProducer("localhost:9092")


def test_scrape_platform_result_topic(producer):
    """scrape_platform → tad_scrape_platform_result."""
    assert producer._make_result_topic("scrape_platform") == "tad_scrape_platform_result"


def test_send_bot_message_result_topic(producer):
    """send_bot_message → tad_send_bot_message_result."""
    assert producer._make_result_topic("send_bot_message") == "tad_send_bot_message_result"


def test_edit_bot_message_result_topic(producer):
    """edit_bot_message → tad_edit_bot_message_result."""
    assert producer._make_result_topic("edit_bot_message") == "tad_edit_bot_message_result"


def test_delete_bot_message_result_topic(producer):
    """delete_bot_message → tad_delete_bot_message_result."""
    assert producer._make_result_topic("delete_bot_message") == "tad_delete_bot_message_result"


def test_all_result_topics_match_backend_regex(producer):
    """Result-топики должны соответствовать regex tad-backend: tad_.*_result."""
    pattern = re.compile(r"tad_.*_result")
    topics = ["scrape_platform", "send_bot_message", "edit_bot_message", "delete_bot_message"]

    for topic in topics:
        result_topic = producer._make_result_topic(topic)
        assert pattern.match(result_topic), f"{result_topic} doesn't match tad_.*_result"
