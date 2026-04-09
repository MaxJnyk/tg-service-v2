"""
Fernet-шифрование для бот-токенов и session string, которые лежат в БД.

Поддержка ротации ключей через MultiFernet:
  - ENCRYPTION_KEY: текущий ключ (им шифруем новые данные)
  - ENCRYPTION_KEY_OLD: старый ключ (только для расшифровки старых данных)

Как ротировать: ставим ENCRYPTION_KEY_OLD = старый ключ, ENCRYPTION_KEY = новый.
Новые данные шифруются новым ключом. Старые расшифровываются прозрачно.
"""

import re

from cryptography.fernet import Fernet, MultiFernet

from src.config import settings

_fernet: MultiFernet | None = None

# Регулярки для обнаружения секретов в сообщениях об ошибках
_BOT_TOKEN_RE = re.compile(r"\d{8,}:[A-Za-z0-9_-]{30,}")
_FERNET_TOKEN_RE = re.compile(r"gAAAAA[A-Za-z0-9_=-]{50,}")
_SESSION_STRING_RE = re.compile(r"[A-Za-z0-9+/=]{100,}")


def validate_encryption_key() -> None:
    """Падаем сразу при старте, если ENCRYPTION_KEY — дефолтная заглушка или пустой."""
    key = settings.ENCRYPTION_KEY
    if not key or "CHANGE_ME" in key:
        raise RuntimeError(
            "ENCRYPTION_KEY is not set! Generate one with: "
            "python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'"
        )


def _get_fernet() -> MultiFernet:
    global _fernet
    if _fernet is None:
        validate_encryption_key()
        keys = [Fernet(settings.ENCRYPTION_KEY.encode())]
        if settings.ENCRYPTION_KEY_OLD:
            keys.append(Fernet(settings.ENCRYPTION_KEY_OLD.encode()))
        _fernet = MultiFernet(keys)
    return _fernet


def encrypt(value: str) -> str:
    """Зашифровать строку, вернуть base64-токен (текущим ключом)."""
    return _get_fernet().encrypt(value.encode()).decode()


def decrypt(token: str) -> str:
    """Расшифровать base64-токен обратно в строку. Пробует текущий ключ, потом старый."""
    return _get_fernet().decrypt(token.encode()).decode()


def redact_sensitive(text: str, max_length: int = 200) -> str:
    """Вырезать бот-токены, Fernet-токены и session string из сообщений об ошибках."""
    text = _BOT_TOKEN_RE.sub("[REDACTED_BOT_TOKEN]", text)
    text = _FERNET_TOKEN_RE.sub("[REDACTED_FERNET]", text)
    text = _SESSION_STRING_RE.sub("[REDACTED_LONG_B64]", text)
    if len(text) > max_length:
        text = text[:max_length] + "...[truncated]"
    return text


def mask_phone(phone: str) -> str:
    if not phone or len(phone) < 7:
        return "***"
    return phone[:4] + "***" + phone[-4:]
