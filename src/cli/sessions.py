"""
CLI для управления сессиями (Telethon).

Использование:
  python -m src.cli.sessions import --file sessions.json
  python -m src.cli.sessions list
  python -m src.cli.sessions status
"""

import asyncio
import getpass
import json
import logging
from pathlib import Path

import typer

_audit_logger = logging.getLogger("tg-service.audit.cli")
_audit_logger.setLevel(logging.INFO)
if not _audit_logger.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(asctime)s AUDIT %(message)s"))
    _audit_logger.addHandler(_h)


def _audit(action: str, details: str = "") -> None:
    user = getpass.getuser()
    _audit_logger.info("user=%s action=%s %s", user, action, details)


app = typer.Typer(help="Управление Telegram-сессиями")


@app.command("import")
def import_sessions(
    file: Path = typer.Option(..., help="JSON file with sessions"),
) -> None:
    """Импорт сессий из JSON-файла.

    Ожидаемый формат:
    [
      {
        "phone": "+14244371383",
        "session_string": "...",
        "api_id": 12345,
        "api_hash": "abc123",
        "device_info": {"device_model": "Samsung Galaxy S23", "system_version": "Android 14", "app_version": "10.6.2"},
        "role": "scrape"
      }
    ]
    """
    if not file.exists():
        typer.echo(f"Файл не найден: {file}")
        raise typer.Exit(1)

    with open(file) as f:
        sessions = json.load(f)

    _audit("import_sessions", f"file={file} count={len(sessions)}")

    async def _import() -> None:
        from src.modules.accounts.service import AccountService

        count = 0
        for s in sessions:
            await AccountService.import_session(
                phone=s["phone"],
                session_string=s["session_string"],
                api_id=s["api_id"],
                api_hash=s["api_hash"],
                device_info=s.get("device_info"),
                proxy_id=s.get("proxy_id"),
                role=s.get("role", "scrape"),
            )
            count += 1
        _audit("import_sessions_done", f"imported={count}")
        typer.echo(f"Импортировано {count} сессий")

    asyncio.run(_import())


@app.command("list")
def list_sessions(
    role: str | None = typer.Option(None, help="Filter by role: scrape/manage"),
) -> None:
    """Список активных сессий."""
    _audit("list_sessions", f"role={role}")

    async def _list() -> None:
        from src.modules.accounts.service import AccountService
        sessions = await AccountService.list_sessions(role=role)
        if not sessions:
            typer.echo("Нет активных сессий")
            return
        for s in sessions:
            status_icon = "✅" if s["fail_count"] == 0 else "⚠️"
            typer.echo(f"  {status_icon} {s['phone']} [{s['role']}] fails={s['fail_count']}")

    asyncio.run(_list())


@app.command("status")
def status() -> None:
    """Показать summary статуса пула сессий."""
    _audit("session_status")

    async def _status() -> None:
        from src.modules.accounts.service import AccountService
        sessions = await AccountService.list_sessions()
        total = len(sessions)
        scrape = sum(1 for s in sessions if s["role"] == "scrape")
        manage = sum(1 for s in sessions if s["role"] == "manage")
        healthy = sum(1 for s in sessions if s["fail_count"] == 0)
        typer.echo(f"Sessions: {total} total, {scrape} scrape, {manage} manage, {healthy} healthy")

    asyncio.run(_status())


if __name__ == "__main__":
    app()
