"""
Фабрика Telethon-клиентов — создаёт TelegramClient с полным device fingerprint и прокси.

Anti-detect стратегия:
  1. X-Pay JSON содержит реальный fingerprint → используем целиком (device, sdk, lang, app_id/hash)
  2. Нет JSON → выбираем стабильное устройство из DEFAULT-пула (по хешу телефона)
  3. lang_pack, lang_code, system_lang_code передаются Telethon (TG трекает это!)
"""

import hashlib
import gc
import logging
from typing import Any

import socks
from telethon import TelegramClient
from telethon.sessions import StringSession

from src.core.security import decrypt, mask_phone
from src.modules.accounts.models import Proxy, TelegramSession

logger = logging.getLogger(__name__)

# Запасные fingerprint-ы — используются ТОЛЬКО когда нет X-Pay JSON.
# Каждый с полными lang/app параметрами чтобы выглядеть как реальный TDesktop.
DEFAULT_DEVICE_INFOS = [
    {
        "device_model": "Samsung Galaxy S23",
        "system_version": "Android 14",
        "app_version": "10.6.2",
        "lang_code": "en",
        "lang_pack": "android",
        "system_lang_code": "en-US",
    },
    {
        "device_model": "iPhone 15 Pro",
        "system_version": "iOS 17.4",
        "app_version": "10.6.2",
        "lang_code": "en",
        "lang_pack": "ios",
        "system_lang_code": "en-US",
    },
    {
        "device_model": "Xiaomi 14",
        "system_version": "Android 14",
        "app_version": "10.5.5",
        "lang_code": "en",
        "lang_pack": "android",
        "system_lang_code": "en-US",
    },
    {
        "device_model": "Google Pixel 8",
        "system_version": "Android 14",
        "app_version": "10.6.1",
        "lang_code": "en",
        "lang_pack": "android",
        "system_lang_code": "en-US",
    },
    {
        "device_model": "Desktop",
        "system_version": "Windows 10",
        "app_version": "6.6.2 x64",
        "lang_code": "en",
        "lang_pack": "tdesktop",
        "system_lang_code": "en",
    },
    {
        "device_model": "Desktop",
        "system_version": "macOS 14.5",
        "app_version": "10.14.5",
        "lang_code": "en",
        "lang_pack": "macos",
        "system_lang_code": "en-US",
    },
]


def _build_proxy_dict(proxy: Proxy) -> tuple | None:
    if not proxy:
        return None

    proxy_type = socks.SOCKS5 if proxy.protocol == "socks5" else socks.HTTP
    plain_password = decrypt(proxy.password) if proxy.password else None
    return (proxy_type, proxy.host, proxy.port, True, proxy.username, plain_password)


def _stable_device_for_phone(phone: str) -> dict[str, Any]:
    """Выбрать устройство детерминированно по хешу телефона.

    Один и тот же телефон всегда получает одно устройство —
    fingerprint не меняется между переподключениями.
    """
    idx = int(hashlib.sha256(phone.encode()).hexdigest(), 16) % len(DEFAULT_DEVICE_INFOS)
    return DEFAULT_DEVICE_INFOS[idx]


def _parse_device_info(raw: dict | None, phone: str = "") -> dict[str, Any]:
    """Распарсить device info из X-Pay JSON или нашего внутреннего формата.

    X-Pay формат:
        {"app_id": 2040, "app_hash": "...", "device": "OA_D-ELITE",
         "sdk": "Windows 10", "app_version": "6.6.2 x64",
         "system_lang_pack": "en", "system_lang_code": "en",
         "lang_pack": "tdesktop", "lang_code": "en"}

    Внутренний формат:
        {"device_model": "Samsung Galaxy S23", "system_version": "Android 14",
         "app_version": "10.6.2"}
    """
    if not raw:
        return _stable_device_for_phone(phone)

    # Определяем X-Pay формат: есть ключи "device" и "sdk"
    if "device" in raw and "sdk" in raw:
        return {
            "device_model": raw["device"],
            "system_version": raw["sdk"],
            "app_version": raw.get("app_version", "10.6.2"),
            "app_id": raw.get("app_id"),
            "app_hash": raw.get("app_hash"),
            "lang_code": raw.get("lang_code", "en"),
            "lang_pack": raw.get("lang_pack", "tdesktop"),
            "system_lang_code": raw.get("system_lang_code", "en"),
        }

    # Внутренний формат
    return {
        "device_model": raw.get("device_model", "Unknown"),
        "system_version": raw.get("system_version", "Unknown"),
        "app_version": raw.get("app_version", "10.6.2"),
        "app_id": raw.get("app_id"),
        "app_hash": raw.get("app_hash"),
        "lang_code": raw.get("lang_code", "en"),
        "lang_pack": raw.get("lang_pack", ""),
        "system_lang_code": raw.get("system_lang_code", "en"),
    }


def create_telethon_client(
    session: TelegramSession,
    proxy: Proxy | None = None,
) -> TelegramClient:
    """Создать TelegramClient из модели TelegramSession.

    Применяется полный fingerprint: device_model, system_version, app_version,
    lang_code, lang_pack, system_lang_code — всё из X-Pay JSON.
    Telegram трекает ВСЕ эти поля для anti-bot детекции.
    """
    session_string = decrypt(session.session_string)
    device_info = _parse_device_info(session.device_info, phone=session.phone)

    # X-Pay JSON может переопределить api_id / api_hash
    api_id = device_info.get("app_id") or session.api_id
    api_hash = device_info.get("app_hash") or decrypt(session.api_hash)

    proxy_config = _build_proxy_dict(proxy) if proxy else None

    client = TelegramClient(
        StringSession(session_string),
        api_id=api_id,
        api_hash=api_hash,
        device_model=device_info["device_model"],
        system_version=device_info["system_version"],
        app_version=device_info["app_version"],
        lang_code=device_info.get("lang_code", "en"),
        system_lang_code=device_info.get("system_lang_code", "en"),
        proxy=proxy_config,
    )

    logger.debug(
        "Created Telethon client: phone=%s device=%s sdk=%s lang=%s api_id=%s proxy=%s",
        mask_phone(session.phone),
        device_info["device_model"],
        device_info["system_version"],
        device_info.get("lang_code", "?"),
        api_id,
        f"{proxy.host}:{proxy.port}" if proxy else "none",
    )

    # По-возможности чистим расшифрованные секреты из локального скоупа
    del session_string
    gc.collect()

    return client
