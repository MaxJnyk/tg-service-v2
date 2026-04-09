"""
Стандартизированные коды ошибок, которые отправляются обратно в tad-backend через Kafka result-сообщения.

Используются в TelegramServiceError.error_code и поле error в TaskResultSchema.
"""

# Ошибки транспорта (Kafka)
NO_HANDLER = "NO_HANDLER"
INTERNAL_ERROR = "INTERNAL_ERROR"
INVALID_PAYLOAD = "INVALID_PAYLOAD"

# Ошибки Telegram-бота (aiogram)
BOT_TOKEN_INVALID = "BOT_TOKEN_INVALID"
BOT_BLOCKED = "BOT_BLOCKED"
BOT_NOT_ADMIN = "BOT_NOT_ADMIN"
BOT_RATE_LIMITED = "BOT_RATE_LIMITED"
BOT_CHAT_NOT_FOUND = "BOT_CHAT_NOT_FOUND"

# Ошибки Telegram-юзербота (Telethon)
SESSION_BANNED = "SESSION_BANNED"
SESSION_FLOOD_WAIT = "SESSION_FLOOD_WAIT"
SESSION_NOT_AVAILABLE = "SESSION_NOT_AVAILABLE"

# Ошибки прокси
PROXY_DEAD = "PROXY_DEAD"
PROXY_AUTH_FAILED = "PROXY_AUTH_FAILED"

# Ошибки аккаунтов (нет активных)
NO_ACTIVE_BOT = "NO_ACTIVE_BOT"
NO_ACTIVE_SESSION = "NO_ACTIVE_SESSION"
ALL_BOTS_FAILED = "ALL_BOTS_FAILED"

# Идемпотентность
DUPLICATE_REQUEST = "DUPLICATE_REQUEST"
