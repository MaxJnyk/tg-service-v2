"""
Tests for KafkaTaskConsumer — manual commit, deserialization, error handling.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import orjson
import pytest

from src.transport.consumer import KafkaTaskConsumer


def _make_msg(topic: str = "test_topic", value: dict | None = None, partition: int = 0, offset: int = 0) -> SimpleNamespace:
    """Create a fake Kafka message."""
    payload = value or {"request_id": "req-1", "payload": {}}
    return SimpleNamespace(
        topic=topic,
        partition=partition,
        offset=offset,
        value=orjson.dumps(payload),
    )


@pytest.fixture
def consumer_deps():
    router = MagicMock()
    router.dispatch = AsyncMock()
    producer = MagicMock()
    producer.send_result = AsyncMock()
    return router, producer


@pytest.fixture
def consumer(consumer_deps):
    router, producer = consumer_deps
    c = KafkaTaskConsumer(
        bootstrap_servers="localhost:9092",
        group_id="test-group",
        topics=["test_topic"],
        router=router,
        producer=producer,
    )
    # Mock the internal consumer so we don't need real Kafka
    c._consumer = AsyncMock()
    c._running = True
    return c


class TestDeserialization:
    def test_valid_json(self, consumer):
        data = consumer._deserialize(orjson.dumps({"foo": "bar"}))
        assert data == {"foo": "bar"}

    def test_malformed_json(self, consumer):
        data = consumer._deserialize(b"not json at all!!!")
        assert data is None

    def test_empty_bytes(self, consumer):
        data = consumer._deserialize(b"")
        assert data is None


class TestProcessMessage:
    @pytest.mark.asyncio
    async def test_successful_processing_commits_offset(self, consumer, consumer_deps):
        router, _ = consumer_deps
        msg = _make_msg()

        await consumer._process_message(msg)

        # Handler was called
        router.dispatch.assert_awaited_once()
        # Offset was committed
        consumer._consumer.commit.assert_awaited_once()
        commit_args = consumer._consumer.commit.call_args
        offsets = commit_args[0][0]
        # offset + 1
        assert list(offsets.values())[0] == msg.offset + 1

    @pytest.mark.asyncio
    async def test_malformed_message_still_commits(self, consumer, consumer_deps):
        router, _ = consumer_deps
        msg = SimpleNamespace(
            topic="test_topic",
            partition=0,
            offset=5,
            value=b"not json",
        )

        await consumer._process_message(msg)

        # Handler NOT called
        router.dispatch.assert_not_awaited()
        # But offset IS committed (don't re-process garbage)
        consumer._consumer.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_handler_exception_sends_error_and_commits(self, consumer, consumer_deps):
        router, producer = consumer_deps
        router.dispatch = AsyncMock(side_effect=RuntimeError("boom"))
        msg = _make_msg()

        await consumer._process_message(msg)

        # Error result sent
        producer.send_result.assert_awaited_once()
        call_kwargs = producer.send_result.call_args[1]
        assert "INTERNAL_ERROR" in call_kwargs["error"]
        # Offset committed even on error
        consumer._consumer.commit.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_handler_exception_and_send_error_fails(self, consumer, consumer_deps):
        """If both handler AND error-result-send fail, offset is still committed."""
        router, producer = consumer_deps
        router.dispatch = AsyncMock(side_effect=RuntimeError("boom"))
        producer.send_result = AsyncMock(side_effect=RuntimeError("send failed"))
        msg = _make_msg()

        # Should not raise
        await consumer._process_message(msg)

        # Offset committed even when everything fails
        consumer._consumer.commit.assert_awaited_once()


class TestConsumeLoop:
    @pytest.mark.asyncio
    async def test_stop_breaks_loop(self, consumer, consumer_deps):
        """Setting _running=False should cause the loop to exit after yielding."""
        msgs_yielded = 0

        async def fake_iter():
            nonlocal msgs_yielded
            yield _make_msg(offset=0)
            msgs_yielded += 1
            # After first msg is dispatched, stop the consumer
            consumer._running = False
            yield _make_msg(offset=1)
            msgs_yielded += 1
            # This third message should NOT be yielded
            yield _make_msg(offset=2)
            msgs_yielded += 1

        consumer._consumer.__aiter__ = lambda self: fake_iter()

        await consumer.consume_loop()

        # Loop should have exited — at most 2 messages yielded before _running check
        assert msgs_yielded <= 2


class TestStopMethod:
    @pytest.mark.asyncio
    async def test_stop_waits_for_inflight_tasks(self, consumer):
        """stop() should wait for in-flight tasks before closing consumer."""
        completed = False

        async def slow_task():
            nonlocal completed
            await asyncio.sleep(0.1)
            completed = True

        task = asyncio.create_task(slow_task())
        consumer._tasks.add(task)
        task.add_done_callback(consumer._tasks.discard)

        await consumer.stop()

        assert completed is True
        consumer._consumer.stop.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_stop_without_tasks(self, consumer):
        """stop() with no in-flight tasks should just close consumer."""
        await consumer.stop()
        consumer._consumer.stop.assert_awaited_once()


class TestCommitOffset:
    @pytest.mark.asyncio
    async def test_commit_failure_does_not_raise(self, consumer):
        """Failed commit should log warning but not raise."""
        consumer._consumer.commit = AsyncMock(side_effect=RuntimeError("commit failed"))
        msg = _make_msg()

        # Should not raise
        await consumer._commit_offset(msg)

    @pytest.mark.asyncio
    async def test_commit_without_consumer(self, consumer):
        """Commit with no consumer should be a no-op."""
        consumer._consumer = None
        msg = _make_msg()

        # Should not raise
        await consumer._commit_offset(msg)
