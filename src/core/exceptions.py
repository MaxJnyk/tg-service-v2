"""
Исключения уровня сервиса.

Все ошибки наследуются от TelegramServiceError и содержат error_code,
который отправляется в Kafka result (см. core/error_codes.py).
"""


class TelegramServiceError(Exception):
    """Базовое исключение для всех ошибок сервиса."""

    def __init__(self, message: str, error_code: str = "INTERNAL_ERROR") -> None:
        self.error_code = error_code
        super().__init__(message)


class BotError(TelegramServiceError):
    """Ошибка операции через бота (aiogram)."""
    pass


class SessionError(TelegramServiceError):
    """Ошибка операции через юзербот (Telethon)."""
    pass


class ProxyError(TelegramServiceError):
    """Ошибка подключения через прокси."""
    pass


class NoAvailableBotError(TelegramServiceError):
    """Нет активного бота для выполнения операции."""

    def __init__(self, message: str = "No active bot available") -> None:
        super().__init__(message, error_code="NO_ACTIVE_BOT")


class NoAvailableSessionError(TelegramServiceError):
    """Нет активной Telethon-сессии."""

    def __init__(self, message: str = "No active session available") -> None:
        super().__init__(message, error_code="NO_ACTIVE_SESSION")
