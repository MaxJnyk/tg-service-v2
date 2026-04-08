from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Kafka
    KAFKA_BOOTSTRAP_SERVERS: str = "kafka:9092"
    KAFKA_GROUP_ID: str = "tg-service-v2"
    KAFKA_TOPICS: list[str] = Field(default=[
        "scrape_platform",
        "send_bot_message",
        "edit_bot_message",
        "delete_bot_message",
    ])

    # Database
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/tg_service"

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    # Security
    ENCRYPTION_KEY: str = "CHANGE_ME_32_BYTES_BASE64_KEY_HERE"

    # Telegram pools
    BOT_POOL_MAX_SIZE: int = 50
    SESSION_POOL_MAX_SIZE: int = 100  # 100 sessions for 1000 platforms (10 per account)

    # Scraping
    MAX_MSG_ANALYZE: int = 200

    # Consumer concurrency (0 = sequential, N = max N tasks in parallel)
    CONSUMER_CONCURRENCY: int = 10

    # Monitoring
    LOG_LEVEL: str = "INFO"
    METRICS_PORT: int = 9090

    # Sentry (error tracking + alerting)
    SENTRY_DSN: str = ""  # Leave empty to disable Sentry

    # Graceful shutdown
    SHUTDOWN_TIMEOUT: int = 30


settings = Settings()
