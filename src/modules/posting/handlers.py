"""
Kafka handlers for posting topics:
  - send_bot_message
  - edit_bot_message
  - delete_bot_message

Each handler:
  1. Checks idempotency (all operations — prevents Kafka redelivery issues)
  2. Parses payload from TaskRequestSchema
  3. Calls PostingService
  4. Sends result back via KafkaResultProducer
"""

import logging

from src.core.exceptions import TelegramServiceError
from src.infrastructure.redis import get_redis
from src.modules.posting.service import PostingService
from src.transport.producer import KafkaResultProducer
from src.transport.schemas import TaskRequestSchema

logger = logging.getLogger(__name__)

_IDEMPOTENCY_TTL = 86400  # 24h


async def _check_idempotency(request_id: str) -> bool:
    """Return True if this request_id was already processed (duplicate)."""
    key = f"tg_idem:post:{request_id}"
    redis = get_redis()
    result = await redis.set(key, "1", nx=True, ex=_IDEMPOTENCY_TTL)
    return result is None  # None means key already existed → duplicate


async def _send_error(
    topic: str,
    request: TaskRequestSchema,
    producer: KafkaResultProducer,
    exc: TelegramServiceError,
) -> None:
    """Send error result — shared by all posting handlers."""
    logger.error("%s failed: %s (code=%s)", topic, exc, exc.error_code)
    await producer.send_result(
        original_topic=topic,
        request=request,
        error=f"[{exc.error_code}] {exc}",
    )


def _parse_platform_and_chat(payload: dict) -> tuple[dict, str | int]:
    """Extract platform dict and resolved chat_id from handler payload."""
    platform = payload.get("platform", {})
    raw_chat = platform.get("internal_id") or platform.get("url", "")
    return platform, PostingService.resolve_chat_id(raw_chat)


def create_posting_handlers(posting_service: PostingService) -> dict:
    """Create handler functions that close over the posting service."""

    async def handle_send_bot_message(
        request: TaskRequestSchema,
        producer: KafkaResultProducer,
    ) -> None:
        if await _check_idempotency(str(request.request_id)):
            logger.warning("send_bot_message: duplicate request_id=%s, skipping", request.request_id)
            return

        payload = request.payload or {}
        platform, chat_id = _parse_platform_and_chat(payload)
        message = payload.get("message", {})

        try:
            result = await posting_service.send_message(
                chat_id=chat_id,
                text=message.get("text", ""),
                platform_id=str(platform.get("id", "")),
                media=message.get("media"),
                markup=message.get("markup"),
                parse_mode=message.get("parse_mode"),
            )
            await producer.send_result(
                original_topic="send_bot_message",
                request=request,
                payload=result,
            )
        except TelegramServiceError as exc:
            await _send_error("send_bot_message", request, producer, exc)

    async def handle_edit_bot_message(
        request: TaskRequestSchema,
        producer: KafkaResultProducer,
    ) -> None:
        if await _check_idempotency(str(request.request_id)):
            logger.warning("edit_bot_message: duplicate request_id=%s, skipping", request.request_id)
            return

        payload = request.payload or {}
        platform, chat_id = _parse_platform_and_chat(payload)
        message = payload.get("message", {})
        message_id = payload.get("message_id") or message.get("message_id")

        if not message_id:
            await producer.send_result(
                original_topic="edit_bot_message",
                request=request,
                error="[INVALID_PAYLOAD] message_id is required",
            )
            return

        try:
            result = await posting_service.edit_message(
                chat_id=chat_id,
                message_id=int(message_id),
                text=message.get("text", ""),
                platform_id=str(platform.get("id", "")),
                media=message.get("media"),
                markup=message.get("markup"),
                parse_mode=message.get("parse_mode"),
            )
            await producer.send_result(
                original_topic="edit_bot_message",
                request=request,
                payload=result,
            )
        except TelegramServiceError as exc:
            await _send_error("edit_bot_message", request, producer, exc)

    async def handle_delete_bot_message(
        request: TaskRequestSchema,
        producer: KafkaResultProducer,
    ) -> None:
        if await _check_idempotency(str(request.request_id)):
            logger.warning("delete_bot_message: duplicate request_id=%s, skipping", request.request_id)
            return

        payload = request.payload or {}
        platform, chat_id = _parse_platform_and_chat(payload)
        message = payload.get("message", {})
        message_id = message.get("message_id")

        if not message_id:
            await producer.send_result(
                original_topic="delete_bot_message",
                request=request,
                error="[INVALID_PAYLOAD] message_id is required",
            )
            return

        try:
            result = await posting_service.delete_message(
                chat_id=chat_id,
                message_id=int(message_id),
                platform_id=str(platform.get("id", "")),
            )
            await producer.send_result(
                original_topic="delete_bot_message",
                request=request,
                payload=result,
            )
        except TelegramServiceError as exc:
            await _send_error("delete_bot_message", request, producer, exc)

    return {
        "send_bot_message": handle_send_bot_message,
        "edit_bot_message": handle_edit_bot_message,
        "delete_bot_message": handle_delete_bot_message,
    }
