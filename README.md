# tg-service-v2

> TAD Telegram Service v2.2 — Kafka-совместимая замена tg-messenger-service + accounting-service
>
> Микросервис для постинга в Telegram-каналы и парсинга статистики через ботов (aiogram) и юзерботов (Telethon).

## Что заменяет

| Старый сервис | Статус |
|---------------|--------|
| tg-messenger-service (msg-app + msg-worker) | **Заменён** |
| accounting-service (acc-app + acc-worker) | **Заменён** |
| accounting-service-ui (Vue.js) | **Заменён** (CLI вместо UI) |

## Архитектура

- **Kafka consumer/producer** — совместим с `tad-backend` (без изменений на бекенде)
- **Своя PostgreSQL** — таблицы `bot_accounts`, `telegram_sessions`, `proxies`
- **Свой Redis** — идемпотентность, rate limiting
- **Нет HTTP API** — только Kafka + CLI + Prometheus метрики на порту 9090

## Быстрый старт

```bash
# 1. Копируем env
cp .env.example .env
# Редактируем .env — задаём ENCRYPTION_KEY, адрес Kafka и т.д.

# 2. Запускаем контейнеры
docker compose up -d

# 3. Накатываем миграции
docker compose exec tg-service alembic upgrade head

# 4. Импортируем сессии и прокси
docker compose exec tg-service python -m src.cli.sessions import --file /data/sessions.json
docker compose exec tg-service python -m src.cli.proxies import --file /data/proxies.txt
```

## Kafka топики (читаемые)

| Топик | Обработчик | Результат-топик |
|-------|------------|-----------------|
| `scrape_platform` | ScrapingService | `tad_scrape_platform_result` |
| `send_bot_message` | PostingService | `tad_send_bot_message_result` |
| `edit_bot_message` | PostingService | `tad_edit_bot_message_result` |
| `delete_bot_message` | PostingService | `tad_delete_bot_message_result` |

## CLI

```bash
# Сессии
python -m src.cli.sessions import --file sessions.json
python -m src.cli.sessions list
python -m src.cli.sessions status

# Прокси
python -m src.cli.proxies add --host 1.2.3.4 --port 1080 --protocol socks5
python -m src.cli.proxies import --file proxies.txt
python -m src.cli.proxies list
python -m src.cli.proxies check
```

## Разработка

```bash
# Установка dev-зависимостей
uv pip install -e ".[dev]"

# Запуск тестов
pytest tests/ -v

# Линтинг
ruff check src/
```

## Структура проекта

```
src/
├── config.py                    # Pydantic-настройки
├── main.py                      # Точка входа (Kafka consumer loop)
├── transport/                   # Kafka transport layer
│   ├── schemas.py               # TaskRequestSchema, TaskResultSchema
│   ├── consumer.py              # KafkaTaskConsumer (ручной коммит)
│   ├── producer.py              # KafkaResultProducer
│   └── router.py                # TopicRouter (topic → handler)
├── infrastructure/
│   ├── database.py              # AsyncEngine + сессии
│   └── redis.py                 # Redis connection pool
├── modules/
│   ├── accounts/                # Своя БД: BotAccount, TelegramSession, Proxy
│   │   ├── models.py
│   │   ├── repository.py
│   │   ├── service.py
│   │   └── importer.py
│   ├── posting/                 # Постинг через aiogram-ботов
│   │   ├── bot_pool.py
│   │   ├── service.py
│   │   ├── handlers.py
│   │   └── retry.py
│   ├── scraping/                # Парсинг через Telethon
│   │   ├── telethon_client.py
│   │   ├── session_pool.py
│   │   ├── proxy_manager.py
│   │   ├── service.py
│   │   └── handlers.py
│   └── billing/
│       └── idempotency.py
├── core/
│   ├── error_codes.py           # Коды ошибок
│   ├── exceptions.py            # Исключения сервиса
│   ├── security.py              # Шифрование (Fernet)
│   ├── metrics.py               # Prometheus метрики
│   └── logging.py               # Структурированное логирование
└── cli/
    ├── sessions.py              # CLI управление сессиями
    └── proxies.py               # CLI управление прокси
```
