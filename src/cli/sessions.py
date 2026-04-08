"""
CLI for session management.

Usage:
  python -m src.cli.sessions import --file sessions.json
  python -m src.cli.sessions list
  python -m src.cli.sessions status
"""

import asyncio
import json
from pathlib import Path

import typer

app = typer.Typer(help="Telegram session management")


@app.command("import")
def import_sessions(
    file: Path = typer.Option(..., help="JSON file with sessions"),
) -> None:
    """Import sessions from a JSON file.

    Expected format:
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
        typer.echo(f"File not found: {file}")
        raise typer.Exit(1)

    with open(file) as f:
        sessions = json.load(f)

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
        typer.echo(f"Imported {count} sessions")

    asyncio.run(_import())


@app.command("list")
def list_sessions(
    role: str | None = typer.Option(None, help="Filter by role: scrape/manage"),
) -> None:
    """List active sessions."""
    async def _list() -> None:
        from src.modules.accounts.service import AccountService
        sessions = await AccountService.list_sessions(role=role)
        if not sessions:
            typer.echo("No active sessions")
            return
        for s in sessions:
            status_icon = "✅" if s["fail_count"] == 0 else "⚠️"
            typer.echo(f"  {status_icon} {s['phone']} [{s['role']}] fails={s['fail_count']}")

    asyncio.run(_list())


@app.command("status")
def status() -> None:
    """Show session pool status summary."""
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
