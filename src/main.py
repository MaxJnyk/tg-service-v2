"""
Точка входа tg-service-v2.

Жизненный цикл:
  1. Запускаем Kafka producer
  2. Регистрируем обработчики в TopicRouter
  3. Запускаем Kafka consumer
  4. Крутим consume loop
  5. По SIGTERM/SIGINT → graceful shutdown:
     a. Стоп consumer (не принимаем новых сообщений)
     b. Ждём завершения текущих задач (SHUTDOWN_TIMEOUT)
     c. Закрываем пулы Telegram-клиентов
     d. Стоп producer
     e. Закрываем БД + Redis
"""

import asyncio
import logging
import signal

import sentry_sdk
from prometheus_client import start_http_server

from src.config import settings
import src.core.healthcheck as healthcheck_mod
from src.core.healthcheck import start_healthcheck_server
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


# Глобальные пулы (создаются один раз, закрываются при shutdown)
bot_pool = BotPool(max_size=settings.BOT_POOL_MAX_SIZE)
session_pool = SessionPool(max_size=settings.SESSION_POOL_MAX_SIZE)


def _register_handlers(router: TopicRouter) -> None:
    """Регистрация обработчиков. Новые модули добавлять сюда."""
    # Обработчики постинга (send/edit/delete через бота)
    rate_limiter = RateLimiter(get_redis())
    posting_service = PostingService(bot_pool, rate_limiter=rate_limiter)
    posting_handlers = create_posting_handlers(posting_service)
    for topic, handler in posting_handlers.items():
        router.register(topic, handler)

    # Обработчики парсинга (сбор статистики каналов через Telethon)
    scraping_service = ScrapingService(session_pool)
    scraping_handlers = create_scraping_handlers(scraping_service)
    for topic, handler in scraping_handlers.items():
        router.register(topic, handler)

    logger.info("Handlers registered: %d", router.handler_count)


async def _shutdown(
    consumer: KafkaTaskConsumer,
    producer: KafkaResultProducer,
    main_task: asyncio.Task,
) -> None:
    """Graceful shutdown — 5 шагов завершения."""
    logger.info("SHUTDOWN [1/5] Stopping consumer (no new messages)...")
    await consumer.stop()

    logger.info("SHUTDOWN [2/5] Waiting for current tasks to finish (timeout=%ds)...", settings.SHUTDOWN_TIMEOUT)
    await asyncio.sleep(0.5)  # Allow in-flight tasks to complete

    logger.info("SHUTDOWN [2.5/5] Flushing pending bot usage updates...")
    from src.modules.posting.service import PostingService
    await PostingService._flush_mark_used()

    logger.info("SHUTDOWN [3/5] Closing Telegram pools...")
    await bot_pool.close_all()
    await session_pool.close_all()

    logger.info("SHUTDOWN [4/5] Stopping producer...")
    await producer.stop()

    logger.info("SHUTDOWN [5/5] Closing DB + Redis connections...")
    await close_engine()
    await close_redis()

    logger.info("Shutdown complete.")
    main_task.cancel()


async def main() -> None:
    # Sentry для трекинга ошибок (выключен если SENTRY_DSN пустой)
    if settings.SENTRY_DSN:
        sentry_sdk.init(
            dsn=settings.SENTRY_DSN,
            traces_sample_rate=0.1,  # 10% of transactions for performance monitoring
            environment="production",
            release="tg-service-v2@0.1.0",
        )
        logger.info("Инициализирован Sentry")

    # Prometheus-метрики — только localhost (скрейпится изнутри сети)
    start_http_server(settings.METRICS_PORT, addr="127.0.0.1")
    logger.info("Prometheus metrics on 127.0.0.1:%d", settings.METRICS_PORT)

    # Транспортный слой
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

    # Healthcheck-сервер (readiness probe) на METRICS_PORT + 1
    healthcheck_mod._consumer_ref = consumer
    _health_server = await start_healthcheck_server(settings.METRICS_PORT + 1)

    # Обработчики сигналов для graceful shutdown
    loop = asyncio.get_running_loop()
    main_task = asyncio.current_task()
    shutdown = lambda: asyncio.create_task(_shutdown(consumer, producer, main_task))  # noqa: E731
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, shutdown)

    # Mark service as healthy
    service_up.set(1)

    # Основной цикл обработки Kafka-сообщений
    logger.info("tg-service-v2 is running. Waiting for Kafka messages...")
    try:
        await consumer.consume_loop()
    except asyncio.CancelledError:
        logger.info("Main loop cancelled")


if __name__ == "__main__":
    asyncio.run(main())
