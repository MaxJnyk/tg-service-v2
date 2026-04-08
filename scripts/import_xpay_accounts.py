"""
Import X-Pay format accounts into tg-service-v2.

X-Pay format:
  +14244371383.session  — SQLite Telethon session file
  +14244371383.json     — device fingerprint (app_id, app_hash, device, sdk, etc.)
  Proxies_*.txt         — host:port:user:pass per line (HTTP proxies)

Usage:
  python scripts/import_xpay_accounts.py --folder "/path/to/Аккаунт ТГ0204"
"""

import asyncio
import json
import logging
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def convert_session_file(session_path: Path) -> str:
    """Convert SQLite .session file to Telethon StringSession."""
    import sqlite3
    from telethon.sessions import SQLiteSession, StringSession

    # Copy to temp path (telethon needs .session extension)
    import tempfile, shutil
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp) / "session.session"
        shutil.copy(session_path, tmp_path)

        sqlite_session = SQLiteSession(str(tmp_path.with_suffix("")))
        string_session = StringSession.save(sqlite_session)
        return string_session


async def import_all(folder: Path) -> None:
    from src.modules.accounts.service import AccountService
    from src.infrastructure.database import close_engine

    # 1. Load proxies
    proxy_ids: list[str] = []
    proxy_files = list(folder.glob("Proxies_*.txt"))
    if proxy_files:
        proxy_file = proxy_files[0]
        logger.info("Loading proxies from %s", proxy_file.name)
        lines = proxy_file.read_text().strip().splitlines()
        for line in lines:
            line = line.strip()
            if not line:
                continue
            parts = line.split(":")
            if len(parts) < 2:
                continue
            host, port = parts[0], int(parts[1])
            username = parts[2] if len(parts) > 2 else None
            password = parts[3] if len(parts) > 3 else None

            pid = await AccountService.add_proxy(
                host=host,
                port=port,
                protocol="http",
                username=username,
                password=password,
            )
            proxy_ids.append(pid)
            logger.info("  Proxy: %s:%d (id=%s)", host, port, pid)
    else:
        logger.warning("No proxy file found in %s", folder)

    # 2. Load sessions
    session_files = sorted(folder.glob("*.session"))
    proxy_cycle = iter(proxy_ids) if proxy_ids else iter([None] * 100)

    for session_file in session_files:
        phone = session_file.stem  # e.g. +14244371383
        json_file = folder / f"{phone}.json"

        if not json_file.exists():
            logger.warning("No JSON for %s, skipping", phone)
            continue

        device_info = json.loads(json_file.read_text())

        # Convert .session → StringSession
        try:
            session_string = convert_session_file(session_file)
        except Exception as e:
            logger.error("Failed to convert session %s: %s", phone, e)
            continue

        proxy_id = next(proxy_cycle, None)

        sid = await AccountService.import_session(
            phone=phone,
            session_string=session_string,
            api_id=device_info["app_id"],
            api_hash=device_info["app_hash"],
            device_info=device_info,
            proxy_id=proxy_id,
            role="scrape",
        )
        logger.info(
            "  Session: %s → id=%s proxy=%s device=%s",
            phone, sid, proxy_id, device_info.get("device", "unknown")
        )

    await close_engine()
    logger.info("Done.")


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Import X-Pay accounts into tg-service-v2")
    parser.add_argument("--folder", required=True, help="Path to folder with .session/.json files")
    args = parser.parse_args()

    folder = Path(args.folder)
    if not folder.exists():
        logger.error("Folder not found: %s", folder)
        sys.exit(1)

    asyncio.run(import_all(folder))


if __name__ == "__main__":
    main()
