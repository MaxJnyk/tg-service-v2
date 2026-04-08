"""
Fernet encryption for bot tokens and session strings stored in DB.
"""

from cryptography.fernet import Fernet

from src.config import settings

_fernet: Fernet | None = None


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        _fernet = Fernet(settings.ENCRYPTION_KEY.encode())
    return _fernet


def encrypt(value: str) -> str:
    """Encrypt a string value, return base64 token."""
    return _get_fernet().encrypt(value.encode()).decode()


def decrypt(token: str) -> str:
    """Decrypt a base64 token, return original string."""
    return _get_fernet().decrypt(token.encode()).decode()
