"""
Tests for KafkaResultProducer — result topic naming and serialization.
"""

import pytest

from src.transport.producer import KafkaResultProducer


class TestResultTopicNaming:
    def test_scrape_platform(self):
        producer = KafkaResultProducer("localhost:9092")
        assert producer._make_result_topic("scrape_platform") == "tad_scrape_platform_result"

    def test_send_bot_message(self):
        producer = KafkaResultProducer("localhost:9092")
        assert producer._make_result_topic("send_bot_message") == "tad_send_bot_message_result"

    def test_edit_bot_message(self):
        producer = KafkaResultProducer("localhost:9092")
        assert producer._make_result_topic("edit_bot_message") == "tad_edit_bot_message_result"

    def test_delete_bot_message(self):
        producer = KafkaResultProducer("localhost:9092")
        assert producer._make_result_topic("delete_bot_message") == "tad_delete_bot_message_result"

    def test_matches_backend_regex(self):
        """Result topics must match tad-backend's regex: tad_.*_result"""
        import re
        pattern = re.compile(r"tad_.*_result")
        producer = KafkaResultProducer("localhost:9092")

        for topic in ["scrape_platform", "send_bot_message", "edit_bot_message", "delete_bot_message"]:
            result_topic = producer._make_result_topic(topic)
            assert pattern.match(result_topic), f"{result_topic} doesn't match tad_.*_result"
