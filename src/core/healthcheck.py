"""
Healthcheck (readiness probe) — проверяет связь с Kafka, БД и Redis.

Отдаёт /healthz как async TCP-эндпоинт на порту METRICS_PORT + 1.
Возвращает 200 если все зависимости живы, 503 если что-то упало.

Rate limit: 1 запрос/сек (защита от спама).
Заголовки безопасности: nosniff, no-store.
"""

import asyncio
import logging
import time
from typing import Any

import orjson
from sqlalchemy import text

_last_check_time: float = 0.0
_MIN_CHECK_INTERVAL = 1.0  # секунд между проверками (rate limit)

from src.infrastructure.database import async_session_factory
from src.infrastructure.redis import get_redis

logger = logging.getLogger(__name__)

# Ссылка на consumer, устанавливается из main.py после старта
_consumer_ref: Any = None


async def _check_db() -> bool:
    try:
        async with async_session_factory() as session:
            await session.execute(text("SELECT 1"))
        return True
    except Exception as exc:
        logger.warning("DB healthcheck failed: %s", exc)
        return False


async def _check_redis() -> bool:
    try:
        redis = get_redis()
        await redis.ping()
        return True
    except Exception as exc:
        logger.warning("Redis healthcheck failed: %s", exc)
        return False


async def check_health() -> dict[str, bool]:
    """ПУСК все проверки параллельно, вернуть статус по каждому компоненту."""
    db_ok, redis_ok = await asyncio.gather(
        _check_db(),
        _check_redis(),
    )

    kafka_ok = True
    if _consumer_ref and hasattr(_consumer_ref, "_consumer") and _consumer_ref._consumer:
        try:
            assignment = _consumer_ref._consumer.assignment()
            kafka_ok = assignment is not None and len(assignment) > 0
        except Exception:
            kafka_ok = False

    return {
        "db": db_ok,
        "redis": redis_ok,
        "kafka": kafka_ok,
    }


async def _handle_request(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    """Минимальный HTTP/1.1-обработчик для /healthz."""
    try:
        request_line = await asyncio.wait_for(reader.readline(), timeout=5)
        # Дочитываем заголовки
        while True:
            line = await asyncio.wait_for(reader.readline(), timeout=5)
            if line == b"\r\n" or line == b"\n" or not line:
                break

        path = request_line.decode().split(" ")[1] if b" " in request_line else "/"

        if path == "/healthz":
            global _last_check_time
            now = time.monotonic()
            if now - _last_check_time < _MIN_CHECK_INTERVAL:
                status, status_text, body = 429, "Too Many Requests", b'{"error":"rate_limited"}'
            else:
                _last_check_time = now
                result = await check_health()
                all_ok = all(result.values())
                status = 200 if all_ok else 503
                body = orjson.dumps(result)
                status_text = "OK" if all_ok else "Service Unavailable"
        else:
            status, status_text, body = 404, "Not Found", b"Not Found"

        response = (
            f"HTTP/1.1 {status} {status_text}\r\n"
            f"Content-Type: application/json\r\n"
            f"Content-Length: {len(body)}\r\n"
            f"X-Content-Type-Options: nosniff\r\n"
            f"Cache-Control: no-store\r\n"
            f"\r\n"
        ).encode() + body

        writer.write(response)
        await writer.drain()
    except Exception:
        pass
    finally:
        writer.close()


async def start_healthcheck_server(port: int) -> asyncio.AbstractServer:
    """ПУСЬК TCP-сервер для healthcheck (только localhost)."""
    server = await asyncio.start_server(_handle_request, "127.0.0.1", port)
    logger.info("Запущен healthcheck-сервер на 127.0.0.1:%d (/healthz)", port)
    return server
