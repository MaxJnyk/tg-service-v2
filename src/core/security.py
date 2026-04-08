"""
Fernet encryption for bot tokens and session strings stored in DB.

Supports key rotation via MultiFernet:
  - ENCRYPTION_KEY: current key (used for new encryptions)
  - ENCRYPTION_KEY_OLD: previous key (used only for decrypting old data)

To rotate: set ENCRYPTION_KEY_OLD to the old key, set ENCRYPTION_KEY to the new one.
New data will be encrypted with the new key. Old data decrypts transparently.
"""

from cryptography.fernet import Fernet, MultiFernet

from src.config import settings

_fernet: MultiFernet | None = None


def _get_fernet() -> MultiFernet:
    global _fernet
    if _fernet is None:
        keys = [Fernet(settings.ENCRYPTION_KEY.encode())]
        if settings.ENCRYPTION_KEY_OLD:
            keys.append(Fernet(settings.ENCRYPTION_KEY_OLD.encode()))
        _fernet = MultiFernet(keys)
    return _fernet


def encrypt(value: str) -> str:
    """Encrypt a string value, return base64 token (uses current key)."""
    return _get_fernet().encrypt(value.encode()).decode()


def decrypt(token: str) -> str:
    """Decrypt a base64 token, return original string. Tries current key first, then old."""
    return _get_fernet().decrypt(token.encode()).decode()
