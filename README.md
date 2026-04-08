# tg-service-v2

> TAD Telegram Service v2.2 — Kafka-compatible replacement for tg-messenger-service + accounting-service

## What this replaces

| Old service | Status |
|---|---|
| tg-messenger-service (msg-app + msg-worker) | **Replaced** |
| accounting-service (acc-app + acc-worker) | **Replaced** |
| accounting-service-ui (Vue.js) | **Replaced** (CLI instead) |

## Architecture

- **Kafka consumer/producer** — compatible with existing `tad-backend` (no backend changes)
- **Own PostgreSQL** — `bot_accounts`, `telegram_sessions`, `proxies` tables
- **Own Redis** — idempotency, rate limiting
- **No HTTP API** — only Kafka + CLI + Prometheus metrics on port 9090

## Quick start

```bash
# 1. Copy env
cp .env.example .env
# Edit .env — set ENCRYPTION_KEY, Kafka address, etc.

# 2. Start containers
docker compose up -d

# 3. Run migrations
docker compose exec tg-service alembic upgrade head

# 4. Import sessions & proxies
docker compose exec tg-service python -m src.cli.sessions import --file /data/sessions.json
docker compose exec tg-service python -m src.cli.proxies import --file /data/proxies.txt
```

## Kafka topics (consumed)

| Topic | Handler | Result topic |
|---|---|---|
| `scrape_platform` | ScrapingService | `tad_scrape_platform_result` |
| `send_bot_message` | PostingService | `tad_send_bot_message_result` |
| `edit_bot_message` | PostingService | `tad_edit_bot_message_result` |
| `delete_bot_message` | PostingService | `tad_delete_bot_message_result` |

## CLI

```bash
# Sessions
python -m src.cli.sessions import --file sessions.json
python -m src.cli.sessions list
python -m src.cli.sessions status

# Proxies
python -m src.cli.proxies add --host 1.2.3.4 --port 1080 --protocol socks5
python -m src.cli.proxies import --file proxies.txt
python -m src.cli.proxies list
python -m src.cli.proxies check
```

## Development

```bash
# Install dev dependencies
uv pip install -e ".[dev]"

# Run tests
pytest tests/ -v

# Lint
ruff check src/
```

## Project structure

```
src/
├── config.py                    # Pydantic Settings
├── main.py                      # Entry point (Kafka consumer loop)
├── transport/                   # Kafka transport layer
│   ├── schemas.py               # TaskRequestSchema, TaskResultSchema
│   ├── consumer.py              # KafkaTaskConsumer (manual commit)
│   ├── producer.py              # KafkaResultProducer
│   └── router.py                # TopicRouter (topic → handler)
├── infrastructure/
│   ├── database.py              # AsyncEngine + sessions
│   └── redis.py                 # Redis connection pool
├── modules/
│   ├── accounts/                # Own DB: BotAccount, TelegramSession, Proxy
│   │   ├── models.py
│   │   ├── repository.py
│   │   ├── service.py
│   │   └── importer.py
│   ├── posting/                 # Bot posting via aiogram
│   │   ├── bot_pool.py
│   │   ├── service.py
│   │   ├── handlers.py
│   │   └── retry.py
│   ├── scraping/                # Telethon scraping
│   │   ├── telethon_client.py
│   │   ├── session_pool.py
│   │   ├── proxy_manager.py
│   │   ├── service.py
│   │   └── handlers.py
│   └── billing/
│       └── idempotency.py
├── core/
│   ├── error_codes.py
│   ├── exceptions.py
│   ├── security.py
│   ├── metrics.py
│   └── logging.py
└── cli/
    ├── sessions.py
    └── proxies.py
```
