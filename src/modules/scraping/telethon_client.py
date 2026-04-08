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


def create_telethon_client(
    session: TelegramSession,
    proxy: Proxy | None = None,
) -> TelegramClient:
    """Create a TelegramClient from a TelegramSession model."""
    session_string = decrypt(session.session_string)
    device_info = session.device_info or DEFAULT_DEVICE_INFOS[0]

    proxy_config = _build_proxy_dict(proxy) if proxy else None

    client = TelegramClient(
        StringSession(session_string),
        api_id=session.api_id,
        api_hash=session.api_hash,
        device_model=device_info.get("device_model", "Unknown"),
        system_version=device_info.get("system_version", "Unknown"),
        app_version=device_info.get("app_version", "10.6.2"),
        proxy=proxy_config,
    )

    logger.debug(
        "Created Telethon client: phone=%s device=%s proxy=%s",
        session.phone,
        device_info.get("device_model"),
        f"{proxy.host}:{proxy.port}" if proxy else "none",
    )
    return client
