# ПЛАН ДОРАБОТОК tg-service-v2

## ФАКТ: что реально нужно

**Подтверждено от SEO (Александр, X-Pay)**:
> Только TG BOT для постинга, НЕ userbots. Других сценариев не рассматриваем.
> Userbots нужны ТОЛЬКО для скрапинга (сбор статистики), т.к. Bot API не даёт такой функционал.

Изучив tad-backend, вот что я нашёл:

**tad-backend TaskTypes** (то что бекенд РЕАЛЬНО отправляет в Kafka):
```python
class TaskTypes(StrEnum):
    SCRAPE_PLATFORM = "scrape_platform"    # ✅ ЕСТЬ
    NEW_MESSAGE = "send_bot_message"       # ✅ ЕСТЬ
    EDIT_MESSAGE = "edit_bot_message"      # ✅ ЕСТЬ
    DELETE_MESSAGE = "delete_bot_message"  # ✅ ЕСТЬ
```

**check_ownership** — бекенд делает САТУРОМ НАПРЯМУЮ через httpx + HTML parsing описания канала (`confirm_platform_ownership_code`), **НЕ через Kafka**.

**check_platform_admin** — бекенд вызывает `tg_tools.get_platform_description()` напрямую через Telegram Bot API (`bot{token}/getChat`), **НЕ через Kafka**.

Вывод: 23 "недостающие" задачи из tg-messenger-service **бекенд не вызывает**.
Они нужны ТОЛЬКО если мы расширяем TaskTypes в бекенде.

---

## РЕАЛЬНЫЙ ПРИОРИТЕТ: что делаем и зачем

### БЛОК 1 — collect_message_stat + collect_messages (бекенд НЕ вызывает, но НУЖЕН)

Без них `platform_metrics` не заполняются. Бекенд умеет только `scrape_platform` (full scrape).
Нужен periodic stat collection для обновления метрик.

**Решение**: НЕ новый Kafka handler. Вместо этого — **cron-задача внутри tg-service-v2**:

```
# Каждые 6 часов: для всех активных платформ → re-scrape → отправить результат
```

**Что юзаем**:
- `APScheduler` (уже в экосистеме Python, 80K+ stars) — `pip install apscheduler`
- Или проще: `asyncio.create_task` с `while True: await asyncio.sleep(interval)`
- ScrapingService уже всё умеет — просто вызываем periodic

**Файлы**:
- `src/modules/scraping/scheduler.py` — periodic re-scrape логика
- Добавить топик в config для platform list (или запрашивать из бекенда)

**Effort**: 3-4 часа

---

### БЛОК 2 — TaskTypes которые бекенд НАЧНЁТ вызывать (расширение API)

Для этого нужно **сначала** добавить TaskTypes в tad-backend, потом handler в tg-service-v2.

#### 2.1 pin_message
**Зачем**: Бекенд после rotate_auction_post хочет закрепить пост
**Бекенд**: добавить `TaskTypes.PIN_MESSAGE = "pin_bot_message"` + вызов в posting.py
**tg-service-v2**: handler → `bot.pin_chat_message(chat_id, message_id)`
**Либа**: aiogram (уже есть) — `Bot.pin_chat_message()`
**Effort**: 1 час (handler копирует паттерн из delete)

#### 2.2 forward_message
**Зачем**: Пересылка поста в другой канал (кросс-постинг)
**tg-service-v2**: handler → `bot.forward_message(chat_id, from_chat_id, message_id)`
**Либа**: aiogram — `Bot.forward_message()`
**Effort**: 1 час

#### 2.3 subscribe_to_channel / unsubscribe
**Зачем**: Userbot подписывается на приватный канал для скрапинга
**tg-service-v2**: handler → telethon `JoinChannelRequest` / `LeaveChannelRequest`
**Либа**: telethon (уже есть) — `from telethon.tl.functions.channels import JoinChannelRequest`
**Effort**: 2 часа

---

### БЛОК 3 — Архитектурные фиксы (делаем СЕЙЧАС, т.к. влияют на всё)

#### 3.1 Scraping retry (КРИТИЧНО)
Сейчас FloodWait = fail. Нужно: retry с другой сессией.

```python
# scraping/service.py — добавить retry loop как в posting/service.py
for attempt in range(MAX_RETRIES):
    client, session = await self._pool.get_session(role="scrape")
    try:
        return await self._do_scrape(client, username)
    except FloodWaitError:
        await self._pool.mark_flood_wait(session.id, exc.seconds)
        continue  # Следующая сессия
```

**Effort**: 1 час (паттерн уже есть в posting)

#### 3.2 Docker healthcheck
```yaml
# docker-compose.yml
healthcheck:
  test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:9090/metrics')"]
  interval: 30s
  timeout: 5s
  retries: 3
```
Prometheus endpoint уже на 9090 — просто пингуем его.

**Effort**: 5 минут

#### 3.3 Concurrent consumer (НУЖНО при 1000+ задач)
Сейчас: sequential `for msg in consumer → await handler(msg) → commit`.
При 1000 постингов с backoff — bottleneck.

**Решение**: `asyncio.Semaphore(N)` + `asyncio.create_task` + per-message commit.

```python
# consumer.py
sem = asyncio.Semaphore(settings.CONSUMER_CONCURRENCY)  # default 10

async def _process(msg):
    async with sem:
        await self._router.dispatch(msg.topic, request, self._producer)

# consume_loop: fire-and-forget tasks, commit after each
async for msg in self._consumer:
    asyncio.create_task(_process(msg))
    # commit moves to _process after successful handling
```

**Effort**: 2-3 часа (нужно аккуратно с commit ordering)

---

### БЛОК 4 — ~~Userbot posting~~ ОТМЕНЕНО

> Подтверждено SEO: постинг ТОЛЬКО через TG Bot. Userbot posting НЕ нужен.
> Userbots = только скрапинг. Это уже реализовано через SessionPool + ScrapingService.

---

### БЛОК 5 — Account management (P3, низкий приоритет)

change_account_avatar/username/bio, change_channel_*, check_user_status, views_posts, comments.

**Когда**: После того как основной posting + scraping flow стабилен.
**Либы**: telethon — всё уже встроено.

**Конкретные Telethon вызовы**:
```python
# Avatar
from telethon.tl.functions.photos import UploadProfilePhotoRequest
# Username
from telethon.tl.functions.account import UpdateUsernameRequest
# Bio
from telethon.tl.functions.account import UpdateProfileRequest
# Channel
from telethon.tl.functions.channels import EditTitleRequest, EditAboutRequest, EditPhotoRequest
# Views
from telethon.tl.functions.messages import GetMessagesViewsRequest
# Comments
client.send_message(entity, message, reply_to=msg_id)
```

**Effort**: ~8 часов на всё

---

## ПОРЯДОК РАБОТЫ

| # | Что | Effort | Зависимости |
|---|-----|--------|-------------|
| 1 | Scraping retry (3.1) | 1ч | Ничего |
| 2 | Docker healthcheck (3.2) | 5мин | Ничего |
| 3 | Concurrent consumer (3.3) | 2-3ч | Ничего |
| 4 | pin_message handler (2.1) | 1ч | Бекенд: добавить TaskType |
| 5 | forward_message handler (2.2) | 1ч | Бекенд: добавить TaskType |
| 6 | subscribe/unsubscribe (2.3) | 2ч | Бекенд: добавить TaskType |
| 7 | Periodic re-scrape (1) | 3-4ч | Ничего |
| 8 | ~~Userbot posting~~ | — | ОТМЕНЕНО (SEO: только TG Bot) |
| 9 | Account management (5) | 8ч | Бекенд: добавить TaskTypes |

**Шаги 1-3 и 7 делаем СЕЙЧАС** — не зависят от бекенда.
**Шаги 4-6, 8-9** — после расширения TaskTypes в бекенде.

**Итого без бекенд-зависимостей: ~7 часов.**
**Итого с бекендом: ~18 часов.** (было 23, убрали userbot posting)

---

## АРХИТЕКТУРА (итог)

```
ПОСТИНГ:  tad-backend → Kafka → tg-service-v2 → aiogram Bot API → Telegram
СКРАПИНГ: tad-backend → Kafka → tg-service-v2 → telethon Userbot → Telegram
```

- **aiogram** (Bot API) = постинг, пины, форварды, проверки админки
- **telethon** (Userbot) = ТОЛЬКО скрапинг статистики + подписка на каналы
- Новых либ НЕ нужно. Всё есть в pyproject.toml.
