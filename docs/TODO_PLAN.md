# ПЛАН ДОРАБОТОК tg-service-v2

> Что у нас нет и что пиздец как нужно

## СТАТУС: 4/27 задач готово (~15%)

---

## СПРИНТ 1 — P0 КРИТИЧНОЕ (без этого не работает MVP)

### 1.1 collect_message_stat
- **Зачем**: Сбор статистики конкретного сообщения (views, reactions, forwards)
- **Как**: Telethon `client.get_messages()` по message_id → собрать views/reactions/forwards
- **Зависит от**: SessionPool (уже есть)
- **Effort**: 2-3 часа

### 1.2 collect_messages
- **Зачем**: Массовый сбор сообщений канала (для аналитики, контент-анализа)
- **Как**: Telethon `client.iter_messages()` с пагинацией → вернуть list of messages
- **Зависит от**: SessionPool
- **Effort**: 3-4 часа

### 1.3 check_ownership
- **Зачем**: Верификация владения каналом (фронт показывает "Подтвердите владение")
- **Как**: Telethon проверка описания канала на наличие verification code
- **Зависит от**: SessionPool
- **Effort**: 2-3 часа

### 1.4 check_platform_admin
- **Зачем**: Проверка что бот добавлен админом в канал
- **Как**: aiogram `bot.get_chat_member(chat_id, bot.id)` → проверить статус admin
- **Зависит от**: BotPool (уже есть)
- **Effort**: 1-2 часа

### 1.5 subscribe_admin_to_channel
- **Зачем**: Подписка бота-админа на канал (нужно для постинга)
- **Как**: Генерация invite link для бота → инструкция пользователю
- **Зависит от**: BotPool
- **Effort**: 2-3 часа

### 1.6 subscribe_to_channel
- **Зачем**: Подписка userbot аккаунта на канал (нужно для скрапинга приватных)
- **Как**: Telethon `client(JoinChannelRequest(channel))` или через invite hash
- **Зависит от**: SessionPool
- **Effort**: 2-3 часа

**Итого спринт 1: ~15-20 часов работы**

---

## СПРИНТ 2 — P1 ПОЛНЫЙ ФУНКЦИОНАЛ ПОСТИНГА

### 2.1 new_message (userbot)
- **Зачем**: Постинг через Telethon (не через бота) — для каналов без бота
- **Как**: Telethon `client.send_message()` с media/markup support
- **Зависит от**: SessionPool + нужен PostingService для Telethon (новый)
- **Effort**: 4-5 часов

### 2.2 edit_message (userbot)
- **Зачем**: Редактирование через Telethon
- **Как**: Telethon `client.edit_message()`
- **Effort**: 2-3 часа

### 2.3 delete_message (userbot)
- **Зачем**: Удаление через Telethon
- **Как**: Telethon `client.delete_messages()`
- **Effort**: 1-2 часа

### 2.4 pin_message
- **Зачем**: Закрепление поста в канале
- **Как**: aiogram `bot.pin_chat_message()` или Telethon
- **Effort**: 1-2 часа

### 2.5 forward_message
- **Зачем**: Пересылка поста в другой канал
- **Как**: Telethon `client.forward_messages()`
- **Effort**: 2-3 часа

### 2.6 unsubscribe_to_channel + unsubscribe_admin_from_channel
- **Зачем**: Отписка аккаунтов/ботов от каналов
- **Как**: Telethon `client(LeaveChannelRequest())` / aiogram leave
- **Effort**: 2-3 часа

### 2.7 scrape_platform_priority
- **Зачем**: Приоритетный скрапинг (обходит очередь)
- **Как**: Тот же handler что scrape_platform, но с отдельным Kafka топиком
- **Effort**: 1 час

**Итого спринт 2: ~15-20 часов работы**

---

## СПРИНТ 3 — P2 РАСШИРЕННЫЙ ФУНКЦИОНАЛ

### 3.1 add_comment_to_message + add_reply_to_comment
- **Зачем**: Комментирование постов (engagement)
- **Как**: Telethon `client.send_message(reply_to=msg_id)`
- **Effort**: 3-4 часа

### 3.2 change_account_* (avatar, username, bio)
- **Зачем**: Управление профилями аккаунтов
- **Как**: Telethon `UpdateProfileRequest`, `UpdateUsernameRequest`, photos.UploadProfilePhoto
- **Effort**: 4-5 часов

### 3.3 change_channel_* (username, avatar, bio)
- **Зачем**: Управление каналами
- **Как**: Telethon `EditTitleRequest`, `EditAboutRequest`, `EditPhotoRequest`
- **Effort**: 4-5 часов

### 3.4 check_user_status
- **Зачем**: Проверка статуса пользователя (banned, deleted, etc.)
- **Как**: Telethon `client.get_entity(user_id)`
- **Effort**: 1-2 часа

### 3.5 views_posts
- **Зачем**: Накрутка просмотров (marketing)
- **Как**: Telethon `GetMessagesViewsRequest`
- **Effort**: 2-3 часа

**Итого спринт 3: ~15-20 часов работы**

---

## СПРИНТ 4 — АРХИТЕКТУРНЫЕ УЛУЧШЕНИЯ

### 4.1 Parallel consumer (concurrent message processing)
- **Зачем**: Убрать bottleneck sequential processing
- **Как**: asyncio.Semaphore + parallel dispatch (сохраняя per-chat ordering)
- **Effort**: 4-5 часов

### 4.2 Scraping retry logic
- **Зачем**: FloodWait → retry с другой сессией (как в posting)
- **Effort**: 2-3 часа

### 4.3 Proxy health check — полная проверка
- **Зачем**: TCP-only недостаточно, нужно проверять SOCKS5/HTTP handshake
- **Effort**: 2-3 часа

### 4.4 Docker healthcheck + /health endpoint
- **Зачем**: Kubernetes readiness/liveness
- **Effort**: 1-2 часа

### 4.5 Backend: reuse Kafka producer
- **Зачем**: Не создавать TCP соединение на каждое сообщение
- **Где**: tad-backend → MessangerTaskBrokerAsync._produce()
- **Effort**: 2-3 часа

**Итого спринт 4: ~12-16 часов работы**

---

## ОБЩИЙ TIMELINE

| Спринт | Что | Часов | Приоритет |
|--------|-----|-------|-----------|
| 1 | P0: MVP задачи (6 handlers) | ~18 | 🔴 ASAP |
| 2 | P1: Полный постинг (7 handlers) | ~18 | ⚠️ Следом |
| 3 | P2: Расширенный функционал (5+ handlers) | ~18 | ℹ️ Потом |
| 4 | Архитектурные улучшения | ~14 | ⚠️ Параллельно |

**Итого: ~68 часов** = ~8-9 рабочих дней на 100% покрытие.

---

## ПОРЯДОК РАБОТЫ

1. **Сейчас**: Импортировать аккаунты от SEO (`import_xpay_accounts.py`)
2. **Спринт 1**: P0 задачи — без них фронт не может верифицировать каналы и собирать статистику
3. **Спринт 2**: Полный постинг — userbot posting для каналов без бота
4. **Спринт 4**: Архитектурные улучшения (можно параллельно со спринтами 2-3)
5. **Спринт 3**: Расширенный функционал (comments, profile management, views)
