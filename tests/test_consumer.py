"""
Тесты для KafkaTaskConsumer — commits, error handling, graceful shutdown
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from aiokafka.structs import TopicPartition

from src.transport.consumer import KafkaTaskConsumer


# =============================================================================
# Fixtures
# =============================================================================
@pytest.fixture
def consumer_deps():
    """Депенденси для KafkaTaskConsumer."""
    router = MagicMock()
    router.handlers = {}
    
    producer = MagicMock()
    producer.send_result = AsyncMock()
    
    return {
        "bootstrap_servers": "localhost:9092",
        "group_id": "test-group",
        "topics": ["scrape_platform"],
        "router": router,
        "producer": producer,
    }


@pytest.fixture
def consumer(consumer_deps):
    """Фикстура для KafkaTaskConsumer."""
    return KafkaTaskConsumer(
        bootstrap_servers=consumer_deps["bootstrap_servers"],
        group_id=consumer_deps["group_id"],
        topics=consumer_deps["topics"],
        router=consumer_deps["router"],
        producer=consumer_deps["producer"],
    )


@pytest.fixture
def mock_kafka_message():
    """Создать мок Kafka message."""
    def _make(topic="scrape_platform", partition=0, offset=42, value=b'{}'):
        msg = MagicMock()
        msg.topic = topic
        msg.partition = partition
        msg.offset = offset
        msg.value = value
        msg.key = None
        msg.headers = []
        return msg
    return _make


# =============================================================================
# Offset Commit Tests
# =============================================================================
@pytest.mark.asyncio
async def test_successful_message_commits_offset(consumer, consumer_deps, mock_kafka_message):
    """Успешная обработка должна коммитить offset."""
    consumer._consumer = AsyncMock(spec=AIOKafkaConsumer)
    consumer._consumer.commit = AsyncMock()
    
    msg = mock_kafka_message(value=b'{"request_id": "test-001", "payload": {}}')
    
    # Mock router to succeed
    consumer_deps["router"].dispatch = AsyncMock()
    
    await consumer._process_message(msg)
    
    consumer._consumer.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_error_message_commits_offset(consumer, consumer_deps, mock_kafka_message):
    """При ошибке offset всё равно коммитится (чтобы не retry вечно)."""
    consumer._consumer = AsyncMock(spec=AIOKafkaConsumer)
    consumer._consumer.commit = AsyncMock()
    
    msg = mock_kafka_message(value=b'{"request_id": "test-002", "callback_task_name": null}')
    
    # Mock router to fail
    consumer_deps["router"].dispatch = AsyncMock(side_effect=RuntimeError("handler failed"))
    
    # Should not raise - error is caught internally
    await consumer._process_message(msg)
    
    # Offset is committed in finally
    consumer._consumer.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_parse_error_commits_offset(consumer, mock_kafka_message):
    """Parse error должен коммитить offset (bad message не retry)."""
    consumer._consumer = AsyncMock(spec=AIOKafkaConsumer)
    consumer._consumer.commit = AsyncMock()
    
    # Invalid JSON
    msg = mock_kafka_message(value=b'not valid json')
    
    await consumer._process_message(msg)
    
    # Should commit to avoid retry
    consumer._consumer.commit.assert_awaited_once()


# =============================================================================
# Error Handling Tests
# =============================================================================
@pytest.mark.asyncio
async def test_producer_sends_error_on_failure(consumer, consumer_deps, mock_kafka_message):
    """При ошибке должен отправляться error result."""
    consumer._consumer = AsyncMock(spec=AIOKafkaConsumer)
    consumer._consumer.commit = AsyncMock()
    
    msg = mock_kafka_message(value=b'{"request_id": "test-002", "callback_task_name": null}')
    consumer_deps["router"].dispatch = AsyncMock(side_effect=RuntimeError("boom"))
    
    # Should not raise - error is caught and handled internally
    await consumer._process_message(msg)
    
    consumer_deps["producer"].send_result.assert_awaited_once()
    call_args = consumer_deps["producer"].send_result.call_args
    assert "error" in str(call_args)


# =============================================================================
# Graceful Shutdown Tests
# =============================================================================
@pytest.mark.asyncio
async def test_shutdown_stops_consumer(consumer):
    """При shutdown consumer должен останавливаться."""
    consumer._consumer = AsyncMock(spec=AIOKafkaConsumer)
    consumer._consumer.stop = AsyncMock()
    
    await consumer.stop()
    
    consumer._consumer.stop.assert_awaited_once()


