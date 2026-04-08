"""
Telethon client factory — creates TelegramClient with full device fingerprint and proxy.

Anti-detect strategy:
  1. X-Pay JSON has real device fingerprint → use it entirely (device, sdk, lang, app_id/hash)
  2. If no JSON → pick random device from DEFAULT pool (never same device for all accounts)
  3. lang_pack, lang_code, system_lang_code are passed to Telethon (TG tracks these!)
"""

import hashlib
import logging
from typing import Any

import socks
from telethon import TelegramClient
from telethon.sessions import StringSession

from src.core.security import decrypt
from src.modules.accounts.models import Proxy, TelegramSession

logger = logging.getLogger(__name__)

# Fallback device fingerprints — used ONLY when X-Pay JSON is missing.
# Each has full lang/app info to look like real TDesktop installs.
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
    return (proxy_type, proxy.host, proxy.port, True, proxy.username, proxy.password)


def _stable_device_for_phone(phone: str) -> dict[str, Any]:
    """Pick a deterministic device based on phone hash.

    Same phone always gets the same fallback device — avoids
    fingerprint changes between reconnects.
    """
    idx = int(hashlib.md5(phone.encode()).hexdigest(), 16) % len(DEFAULT_DEVICE_INFOS)
    return DEFAULT_DEVICE_INFOS[idx]


def _parse_device_info(raw: dict | None, phone: str = "") -> dict[str, Any]:
    """Parse device info from X-Pay JSON format or our internal format.

    X-Pay format:
        {"app_id": 2040, "app_hash": "...", "device": "OA_D-ELITE",
         "sdk": "Windows 10", "app_version": "6.6.2 x64",
         "system_lang_pack": "en", "system_lang_code": "en",
         "lang_pack": "tdesktop", "lang_code": "en"}

    Internal format:
        {"device_model": "Samsung Galaxy S23", "system_version": "Android 14",
         "app_version": "10.6.2"}
    """
    if not raw:
        return _stable_device_for_phone(phone)

    # X-Pay format detection: has "device" and "sdk" keys
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

    # Internal format
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
    """Create a TelegramClient from a TelegramSession model.

    Full fingerprint is applied: device_model, system_version, app_version,
    lang_code, lang_pack, system_lang_code — all from X-Pay JSON.
    Telegram tracks ALL of these fields for anti-bot detection.
    """
    session_string = decrypt(session.session_string)
    device_info = _parse_device_info(session.device_info, phone=session.phone)

    # X-Pay JSON may override api_id / api_hash
    api_id = device_info.get("app_id") or session.api_id
    api_hash = device_info.get("app_hash") or session.api_hash

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
        session.phone,
        device_info["device_model"],
        device_info["system_version"],
        device_info.get("lang_code", "?"),
        api_id,
        f"{proxy.host}:{proxy.port}" if proxy else "none",
    )
    return client
