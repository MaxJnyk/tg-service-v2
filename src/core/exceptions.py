"""
Service-level exceptions.
"""


class TelegramServiceError(Exception):
    """Base exception for all service errors."""

    def __init__(self, message: str, error_code: str = "INTERNAL_ERROR") -> None:
        self.error_code = error_code
        super().__init__(message)


class BotError(TelegramServiceError):
    """Bot operation failed."""
    pass


class SessionError(TelegramServiceError):
    """Telethon session operation failed."""
    pass


class ProxyError(TelegramServiceError):
    """Proxy connection failed."""
    pass


class NoAvailableBotError(TelegramServiceError):
    """No active bot available for the operation."""

    def __init__(self, message: str = "No active bot available") -> None:
        super().__init__(message, error_code="NO_ACTIVE_BOT")


class NoAvailableSessionError(TelegramServiceError):
    """No active Telethon session available."""

    def __init__(self, message: str = "No active session available") -> None:
        super().__init__(message, error_code="NO_ACTIVE_SESSION")
