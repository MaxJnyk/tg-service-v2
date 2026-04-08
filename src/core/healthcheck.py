"""
Readiness probe — checks Kafka consumer, DB, and Redis connectivity.

Serves /healthz as an async TCP endpoint on METRICS_PORT + 1.
Returns 200 if all dependencies are reachable, 503 otherwise.
"""

import asyncio
import logging
from typing import Any

import orjson
from sqlalchemy import text

from src.infrastructure.database import async_session_factory
from src.infrastructure.redis import get_redis

logger = logging.getLogger(__name__)

# Reference to consumer, set by main.py after startup
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
    """Run all health checks concurrently, return per-component status."""
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
    """Minimal HTTP/1.1 handler for /healthz."""
    try:
        request_line = await asyncio.wait_for(reader.readline(), timeout=5)
        # Drain headers
        while True:
            line = await asyncio.wait_for(reader.readline(), timeout=5)
            if line == b"\r\n" or line == b"\n" or not line:
                break

        path = request_line.decode().split(" ")[1] if b" " in request_line else "/"

        if path == "/healthz":
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
            f"\r\n"
        ).encode() + body

        writer.write(response)
        await writer.drain()
    except Exception:
        pass
    finally:
        writer.close()


async def start_healthcheck_server(port: int) -> asyncio.AbstractServer:
    """Start an async TCP server for health checks."""
    server = await asyncio.start_server(_handle_request, "0.0.0.0", port)
    logger.info("Healthcheck server on port %d (/healthz)", port)
    return server
