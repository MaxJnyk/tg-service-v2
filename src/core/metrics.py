"""
Prometheus-метрики для мониторинга.

Скрейпятся Prometheus на METRICS_PORT (127.0.0.1, доступ только изнутри сети).
"""

from prometheus_client import Counter, Gauge, Histogram

# Kafka — счётчики обработки сообщений
kafka_messages_received = Counter(
    "tg_service_kafka_messages_received_total",
    "Total Kafka messages received",
    ["topic"],
)
kafka_messages_processed = Counter(
    "tg_service_kafka_messages_processed_total",
    "Total Kafka messages successfully processed",
    ["topic"],
)
kafka_messages_errors = Counter(
    "tg_service_kafka_messages_errors_total",
    "Total Kafka message processing errors",
    ["topic", "error_code"],
)
kafka_processing_duration = Histogram(
    "tg_service_kafka_processing_seconds",
    "Time to process a Kafka message",
    ["topic"],
    buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0],
)

# Пул ботов
active_bots = Gauge(
    "tg_service_active_bots",
    "Number of active bot instances in pool",
)

# Пул сессий (Telethon)
active_sessions = Gauge(
    "tg_service_active_sessions",
    "Number of active Telethon sessions in pool",
)

# Постинг
posting_operations = Counter(
    "tg_service_posting_operations_total",
    "Total posting operations",
    ["operation"],  # send / edit / delete
)

# Scraping
scraping_operations = Counter(
    "tg_service_scraping_operations_total",
    "Total scraping operations",
)

# Service health
service_up = Gauge(
    "tg_service_up",
    "Service health status (1=healthy)",
)
