from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Kafka — подключение к брокеру сообщений
    KAFKA_BOOTSTRAP_SERVERS: str = "kafka:9092"
    KAFKA_GROUP_ID: str = "tg-service-v2"
    KAFKA_TOPICS: list[str] = Field(default=[
        "scrape_platform",
        "send_bot_message",
        "edit_bot_message",
        "delete_bot_message",
    ])

    # База данных — PostgreSQL (async)
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/tg_service"

    # Redis — идемпотентность, rate limiting, кеш
    REDIS_URL: str = "redis://localhost:6379/0"

    # Безопасность — шифрование токенов и сессий в БД (Fernet)
    ENCRYPTION_KEY: str = "CHANGE_ME_32_BYTES_BASE64_KEY_HERE"
    ENCRYPTION_KEY_OLD: str = ""  # Предыдущий ключ для ротации; пусто если ротации нет

    # Пулы Telegram-клиентов
    BOT_POOL_MAX_SIZE: int = 50
    SESSION_POOL_MAX_SIZE: int = 100  # 100 сессий для 1000 площадок (~10 на аккаунт)

    # Парсинг — кол-во сообщений для анализа статистики канала
    MAX_MSG_ANALYZE: int = 200

    # Конкурентность consumer (0 = последовательно, N = макс N задач параллельно)
    CONSUMER_CONCURRENCY: int = 10

    # Мониторинг
    LOG_LEVEL: str = "INFO"
    METRICS_PORT: int = 9090  # Prometheus /metrics на этом порту

    # Sentry (трекинг ошибок + алерты)
    SENTRY_DSN: str = ""  # Пустая строка = Sentry выключен

    # Graceful shutdown — таймаут ожидания завершения in-flight задач (сек)
    SHUTDOWN_TIMEOUT: int = 30


settings = Settings()
