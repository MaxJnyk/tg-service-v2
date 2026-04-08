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
import sys

from prometheus_client import start_http_server

from src.config import settings
from src.transport.consumer import KafkaTaskConsumer
from src.transport.producer import KafkaResultProducer
from src.transport.router import TopicRouter

logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper()),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("tg-service-v2")


def _register_handlers(router: TopicRouter) -> None:
    """Register topic handlers. Add new handlers here as modules are built."""
    # Day 4: posting handlers
    # from src.modules.posting.handlers import (
    #     handle_send_bot_message,
    #     handle_edit_bot_message,
    #     handle_delete_bot_message,
    # )
    # router.register("send_bot_message", handle_send_bot_message)
    # router.register("edit_bot_message", handle_edit_bot_message)
    # router.register("delete_bot_message", handle_delete_bot_message)

    # Day 7: scraping handlers
    # from src.modules.scraping.handlers import handle_scrape_platform
    # router.register("scrape_platform", handle_scrape_platform)

    logger.info("Handlers registered (currently: %d)", len(router._handlers))


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
    # Will be filled in Day 4+

    logger.info("SHUTDOWN [4/5] Stopping producer...")
    await producer.stop()

    logger.info("SHUTDOWN [5/5] Closing DB + Redis connections...")
    # Will be filled in Day 3

    logger.info("Shutdown complete.")
    loop.stop()


async def main() -> None:
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
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(
            sig,
            lambda: asyncio.create_task(_shutdown(consumer, producer, loop)),
        )

    # Main loop
    logger.info("tg-service-v2 is running. Waiting for Kafka messages...")
    try:
        await consumer.consume_loop()
    except asyncio.CancelledError:
        logger.info("Main loop cancelled")


if __name__ == "__main__":
    asyncio.run(main())
