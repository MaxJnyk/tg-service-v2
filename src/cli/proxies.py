"""
CLI для управления прокси.

Использование:
  python -m src.cli.proxies add --host 1.2.3.4 --port 1080 --protocol socks5
  python -m src.cli.proxies import --file proxies.txt
  python -m src.cli.proxies list
  python -m src.cli.proxies check
"""

import asyncio
import getpass
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


app = typer.Typer(help="Управление прокси")


@app.command("add")
def add_proxy(
    host: str = typer.Option(..., help="Proxy host"),
    port: int = typer.Option(..., help="Proxy port"),
    protocol: str = typer.Option("socks5", help="socks5 or http"),
    username: str | None = typer.Option(None, help="Auth username"),
    password: str | None = typer.Option(None, help="Auth password"),
    country: str | None = typer.Option(None, help="Country code (US, DE, etc.)"),
) -> None:
    """Добавить один прокси."""
    _audit("add_proxy", f"host={host} port={port} protocol={protocol}")

    async def _add() -> None:
        from src.modules.accounts.service import AccountService
        proxy_id = await AccountService.add_proxy(
            host=host, port=port, protocol=protocol,
            username=username, password=password, country_code=country,
        )
        typer.echo(f"Добавлен прокси {host}:{port} (id={proxy_id})")

    asyncio.run(_add())


@app.command("import")
def import_proxies(
    file: Path = typer.Option(..., help="Text file with proxies, one per line: protocol://user:pass@host:port"),
) -> None:
    """Импорт прокси из текстового файла.

    Поддерживаемые форматы:
      socks5://user:pass@1.2.3.4:1080
      http://1.2.3.4:8080
      1.2.3.4:1080  (по умолчанию socks5)
    """
    if not file.exists():
        typer.echo(f"Файл не найден: {file}")
        raise typer.Exit(1)

    lines = file.read_text().strip().splitlines()
    _audit("import_proxies", f"file={file} lines={len(lines)}")

    async def _import() -> None:
        from src.modules.accounts.service import AccountService
        count = 0
        for line in lines:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                parsed = _parse_proxy_line(line)
                await AccountService.add_proxy(**parsed)
                count += 1
            except Exception as exc:
                typer.echo(f"   Skipped: {line} ({exc})")
        typer.echo(f"Импортировано {count} прокси")

    asyncio.run(_import())


@app.command("list")
def list_proxies() -> None:
    """Список всех прокси."""
    _audit("list_proxies")

    async def _list() -> None:
        from src.modules.accounts.service import AccountService
        proxies = await AccountService.list_proxies()
        if not proxies:
            typer.echo("Нет настроенных прокси")
            return
        for p in proxies:
            status = "ОК" if p["is_active"] else "НЕ ОК)"
            latency = f"{p['response_time_ms']}ms" if p["response_time_ms"] else "?"
            typer.echo(f"  {status} {p['protocol']}://{p['host']}:{p['port']} [{latency}] {p['country_code'] or ''}")

    asyncio.run(_list())


@app.command("check")
def check_proxies() -> None:
    """Health check всех прокси."""
    _audit("check_proxies")

    async def _check() -> None:
        from src.modules.scraping.proxy_manager import ProxyManager
        result = await ProxyManager.check_all_proxies()
        typer.echo(result)

    asyncio.run(_check())


def _parse_proxy_line(line: str) -> dict:
    """Распарсить строку прокси: protocol://user:pass@host:port"""
    protocol = "socks5"
    username = None
    password = None

    # Strip protocol
    if "://" in line:
        protocol, line = line.split("://", 1)

    # Strip auth
    if "@" in line:
        auth, line = line.rsplit("@", 1)
        if ":" in auth:
            username, password = auth.split(":", 1)
        else:
            username = auth

    # Host:port
    host, port_str = line.rsplit(":", 1)
    port = int(port_str)
    if not (1 <= port <= 65535):
        raise ValueError(f"Port {port} out of valid range (1-65535)")
    return {
        "host": host,
        "port": port,
        "protocol": protocol,
        "username": username,
        "password": password,
    }


if __name__ == "__main__":
    app()
