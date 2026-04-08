"""
Telethon client factory — creates TelegramClient with device fingerprint and proxy.
"""

import logging
from typing import Any

import socks
from telethon import TelegramClient
from telethon.sessions import StringSession

from src.core.security import decrypt
from src.modules.accounts.models import Proxy, TelegramSession

logger = logging.getLogger(__name__)

# Real device fingerprints (from X-Pay archives)
DEFAULT_DEVICE_INFOS = [
    {
        "device_model": "Samsung Galaxy S23",
        "system_version": "Android 14",
        "app_version": "10.6.2",
    },
    {
        "device_model": "iPhone 15 Pro",
        "system_version": "iOS 17.4",
        "app_version": "10.6.2",
    },
    {
        "device_model": "Xiaomi 14",
        "system_version": "Android 14",
        "app_version": "10.5.5",
    },
    {
        "device_model": "Google Pixel 8",
        "system_version": "Android 14",
        "app_version": "10.6.1",
    },
]


def _build_proxy_dict(proxy: Proxy) -> dict[str, Any] | None:
    if not proxy:
        return None

    proxy_type = socks.SOCKS5 if proxy.protocol == "socks5" else socks.HTTP
    return (proxy_type, proxy.host, proxy.port, True, proxy.username, proxy.password)


def _parse_device_info(raw: dict | None) -> dict[str, Any]:
    """Parse device info from X-Pay JSON format or our internal format.

    X-Pay format:
        {"app_id": 2040, "app_hash": "...", "device": "OA_D-ELITE",
         "sdk": "Windows 10", "app_version": "6.6.2 x64", ...}

    Internal format:
        {"device_model": "Samsung Galaxy S23", "system_version": "Android 14",
         "app_version": "10.6.2"}
    """
    if not raw:
        return DEFAULT_DEVICE_INFOS[0]

    # X-Pay format detection: has "device" and "sdk" keys
    if "device" in raw and "sdk" in raw:
        return {
            "device_model": raw["device"],
            "system_version": raw["sdk"],
            "app_version": raw.get("app_version", "10.6.2"),
            "app_id": raw.get("app_id"),
            "app_hash": raw.get("app_hash"),
        }

    # Internal format
    return {
        "device_model": raw.get("device_model", "Unknown"),
        "system_version": raw.get("system_version", "Unknown"),
        "app_version": raw.get("app_version", "10.6.2"),
        "app_id": raw.get("app_id"),
        "app_hash": raw.get("app_hash"),
    }


def create_telethon_client(
    session: TelegramSession,
    proxy: Proxy | None = None,
) -> TelegramClient:
    """Create a TelegramClient from a TelegramSession model.

    Supports X-Pay JSON device fingerprint format: app_id, app_hash,
    device, sdk, app_version are extracted and passed to Telethon.
    """
    session_string = decrypt(session.session_string)
    device_info = _parse_device_info(session.device_info)

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
        proxy=proxy_config,
    )

    logger.debug(
        "Created Telethon client: phone=%s device=%s api_id=%s proxy=%s",
        session.phone,
        device_info["device_model"],
        api_id,
        f"{proxy.host}:{proxy.port}" if proxy else "none",
    )
    return client
