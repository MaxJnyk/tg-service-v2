"""
Kafka handlers for posting topics:
  - send_bot_message
  - edit_bot_message
  - delete_bot_message

Each handler:
  1. Parses payload from TaskRequestSchema
  2. Calls PostingService
  3. Sends result back via KafkaResultProducer
"""

import logging

from src.core.exceptions import NoAvailableBotError, TelegramServiceError
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
        platform = payload.get("platform", {})
        message = payload.get("message", {})

        raw_chat = platform.get("internal_id") or platform.get("url", "")
        chat_id = PostingService.resolve_chat_id(raw_chat)
        text = message.get("text", "")
        media = message.get("media")
        markup = message.get("markup")
        parse_mode = message.get("parse_mode")

        try:
            result = await posting_service.send_message(
                chat_id=chat_id,
                text=text,
                platform_id=str(platform.get("id", "")),
                media=media,
                markup=markup,
                parse_mode=parse_mode,
            )
            await producer.send_result(
                original_topic="send_bot_message",
                request=request,
                payload=result,
            )
        except NoAvailableBotError as exc:
            logger.error("send_bot_message: no active bot available")
            await producer.send_result(
                original_topic="send_bot_message",
                request=request,
                error=f"[{exc.error_code}] {exc}",
            )
        except TelegramServiceError as exc:
            logger.error("send_bot_message failed: %s (code=%s)", exc, exc.error_code)
            await producer.send_result(
                original_topic="send_bot_message",
                request=request,
                error=f"[{exc.error_code}] {exc}",
            )

    async def handle_edit_bot_message(
        request: TaskRequestSchema,
        producer: KafkaResultProducer,
    ) -> None:
        payload = request.payload or {}
        platform = payload.get("platform", {})
        message = payload.get("message", {})

        raw_chat = platform.get("internal_id") or platform.get("url", "")
        chat_id = PostingService.resolve_chat_id(raw_chat)
        message_id = payload.get("message_id") or message.get("message_id")
        text = message.get("text", "")
        media = message.get("media")
        markup = message.get("markup")
        parse_mode = message.get("parse_mode")

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
                text=text,
                platform_id=str(platform.get("id", "")),
                media=media,
                markup=markup,
                parse_mode=parse_mode,
            )
            await producer.send_result(
                original_topic="edit_bot_message",
                request=request,
                payload=result,
            )
        except NoAvailableBotError as exc:
            logger.error("edit_bot_message: no active bot available")
            await producer.send_result(
                original_topic="edit_bot_message",
                request=request,
                error=f"[{exc.error_code}] {exc}",
            )
        except TelegramServiceError as exc:
            logger.error("edit_bot_message failed: %s (code=%s)", exc, exc.error_code)
            await producer.send_result(
                original_topic="edit_bot_message",
                request=request,
                error=f"[{exc.error_code}] {exc}",
            )

    async def handle_delete_bot_message(
        request: TaskRequestSchema,
        producer: KafkaResultProducer,
    ) -> None:
        payload = request.payload or {}
        platform = payload.get("platform", {})
        message = payload.get("message", {})

        raw_chat = platform.get("internal_id") or platform.get("url", "")
        chat_id = PostingService.resolve_chat_id(raw_chat)
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
        except NoAvailableBotError as exc:
            logger.error("delete_bot_message: no active bot available")
            await producer.send_result(
                original_topic="delete_bot_message",
                request=request,
                error=f"[{exc.error_code}] {exc}",
            )
        except TelegramServiceError as exc:
            logger.error("delete_bot_message failed: %s (code=%s)", exc, exc.error_code)
            await producer.send_result(
                original_topic="delete_bot_message",
                request=request,
                error=f"[{exc.error_code}] {exc}",
            )

    return {
        "send_bot_message": handle_send_bot_message,
        "edit_bot_message": handle_edit_bot_message,
        "delete_bot_message": handle_delete_bot_message,
    }
