"""
tg-service-v2 entry point.

Lifecycle:
  1. Start Kafka producer
  2. Register handlers on TopicRouter
  3. Start Kafka consumer
  4. Run consume loop
  5. On SIGTERM/SIGINT → graceful shutdown:
     a. Stop consumer (stop receiving new messages)
     b. Wait for current task to finish (SHUTDOWN_TIMEOUT)
     c. Close bot pool connections
     d. Stop producer
     e. Close DB + Redis connections
"""

import asyncio
import logging
import signal

import sentry_sdk
from prometheus_client import start_http_server

from src.config import settings
from src.core.logging import setup_logging
from src.core.metrics import service_up
from src.infrastructure.database import close_engine
from src.infrastructure.rate_limiter import RateLimiter
from src.infrastructure.redis import close_redis, get_redis
from src.modules.posting.bot_pool import BotPool
from src.modules.posting.handlers import create_posting_handlers
from src.modules.posting.service import PostingService
from src.modules.scraping.handlers import create_scraping_handlers
from src.modules.scraping.service import ScrapingService
from src.modules.scraping.session_pool import SessionPool
from src.transport.consumer import KafkaTaskConsumer
from src.transport.producer import KafkaResultProducer
from src.transport.router import TopicRouter

setup_logging()
logger = logging.getLogger("tg-service-v2")


# Global instances
bot_pool = BotPool(max_size=settings.BOT_POOL_MAX_SIZE)
session_pool = SessionPool(max_size=settings.SESSION_POOL_MAX_SIZE)


def _register_handlers(router: TopicRouter) -> None:
    """Register topic handlers. Add new handlers here as modules are built."""
    # Posting handlers (Day 4)
    rate_limiter = RateLimiter(get_redis())
    posting_service = PostingService(bot_pool, rate_limiter=rate_limiter)
    posting_handlers = create_posting_handlers(posting_service)
    for topic, handler in posting_handlers.items():
        router.register(topic, handler)

    # Scraping handlers (Day 5-7)
    scraping_service = ScrapingService(session_pool)
    scraping_handlers = create_scraping_handlers(scraping_service)
    for topic, handler in scraping_handlers.items():
        router.register(topic, handler)

    logger.info("Handlers registered: %d", router.handler_count)


async def _shutdown(
    consumer: KafkaTaskConsumer,
    producer: KafkaResultProducer,
    loop: asyncio.AbstractEventLoop,
) -> None:
    """Graceful shutdown — 5 steps."""
    logger.info("SHUTDOWN [1/5] Stopping consumer (no new messages)...")
    await consumer.stop()

    logger.info("SHUTDOWN [2/5] Waiting for current tasks to finish (timeout=%ds)...", settings.SHUTDOWN_TIMEOUT)
    await asyncio.sleep(0.5)  # Allow in-flight task to complete

    logger.info("SHUTDOWN [3/5] Closing Telegram pools...")
    await bot_pool.close_all()
    await session_pool.close_all()

    logger.info("SHUTDOWN [4/5] Stopping producer...")
    await producer.stop()

    logger.info("SHUTDOWN [5/5] Closing DB + Redis connections...")
    await close_engine()
    await close_redis()

    logger.info("Shutdown complete.")
    loop.stop()


async def main() -> None:
    # Sentry error tracking (disabled if SENTRY_DSN is empty)
    if settings.SENTRY_DSN:
        sentry_sdk.init(
            dsn=settings.SENTRY_DSN,
            traces_sample_rate=0.1,  # 10% of transactions for performance monitoring
            environment="production",
            release="tg-service-v2@0.1.0",
        )
        logger.info("Sentry initialized")

    # Prometheus metrics server
    start_http_server(settings.METRICS_PORT)
    logger.info("Prometheus metrics on port %d", settings.METRICS_PORT)

    # Transport layer
    producer = KafkaResultProducer(settings.KAFKA_BOOTSTRAP_SERVERS)
    await producer.start()

    router = TopicRouter()
    _register_handlers(router)

    consumer = KafkaTaskConsumer(
        bootstrap_servers=settings.KAFKA_BOOTSTRAP_SERVERS,
        group_id=settings.KAFKA_GROUP_ID,
        topics=settings.KAFKA_TOPICS,
        router=router,
        producer=producer,
    )
    await consumer.start()

    # Signal handlers for graceful shutdown
    loop = asyncio.get_running_loop()
    shutdown = lambda: asyncio.create_task(_shutdown(consumer, producer, loop))  # noqa: E731
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, shutdown)

    # Mark service as healthy
    service_up.set(1)

    # Main loop
    logger.info("tg-service-v2 is running. Waiting for Kafka messages...")
    try:
        await consumer.consume_loop()
    except asyncio.CancelledError:
        logger.info("Main loop cancelled")


if __name__ == "__main__":
    asyncio.run(main())
