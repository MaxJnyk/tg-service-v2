"""
SQLAlchemy-модели для  БД сервиса.

Три таблицы:
  - bot_accounts — Telegram-боты для постинга
  - proxies — SOCKS5/HTTP прокси
  - telegram_sessions — Telethon-сессии для парсинга

Все секретные поля (bot_token, session_string, api_hash, proxy password)
хранятся зашифрованными через Fernet.
"""

from datetime import datetime
from uuid import uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from src.infrastructure.database import Base


class BotAccount(Base):
    __tablename__ = "bot_accounts"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    bot_token: Mapped[str] = mapped_column(String, nullable=False)    # Зашифрован через Fernet
    name: Mapped[str] = mapped_column(String, nullable=False)  # @botname
    platform_id: Mapped[str | None] = mapped_column(UUID(as_uuid=False), nullable=True)  # связанная платформа
    is_active: Mapped[bool] = mapped_column(default=True)
    fail_count: Mapped[int] = mapped_column(default=0)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    def __repr__(self) -> str:
        return f"<BotAccount name={self.name} active={self.is_active} fails={self.fail_count}>"


class Proxy(Base):
    __tablename__ = "proxies"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    host: Mapped[str] = mapped_column(String, nullable=False)
    port: Mapped[int] = mapped_column(nullable=False)
    protocol: Mapped[str] = mapped_column(String, default="socks5")  # socks5 / http
    username: Mapped[str | None] = mapped_column(String, nullable=True)
    password: Mapped[str | None] = mapped_column(String, nullable=True)    # Зашифрован через Fernet
    country_code: Mapped[str | None] = mapped_column(String(2), nullable=True)  # US, DE, etc.
    is_active: Mapped[bool] = mapped_column(default=True)
    response_time_ms: Mapped[int | None] = mapped_column(nullable=True)
    fail_count: Mapped[int] = mapped_column(default=0)

    sessions: Mapped[list["TelegramSession"]] = relationship(back_populates="proxy")

    def __repr__(self) -> str:
        return f"<Proxy {self.protocol}://{self.host}:{self.port} active={self.is_active}>"


class TelegramSession(Base):
    __tablename__ = "telegram_sessions"

    id: Mapped[str] = mapped_column(UUID(as_uuid=False), primary_key=True, default=lambda: str(uuid4()))
    phone: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    session_string: Mapped[str] = mapped_column(String, nullable=False)    # Зашифрован через Fernet
    api_id: Mapped[int] = mapped_column(nullable=False)
    api_hash: Mapped[str] = mapped_column(String, nullable=False)    # Зашифрован через Fernet
    device_info: Mapped[dict] = mapped_column(JSON, default=dict)  # device fingerprint
    proxy_id: Mapped[str | None] = mapped_column(
        UUID(as_uuid=False), ForeignKey("proxies.id"), nullable=True
    )
    status: Mapped[str] = mapped_column(String, default="active")  # active / cooldown / banned / archived
    role: Mapped[str] = mapped_column(String, default="scrape")  # scrape / manage
    flood_wait_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fail_count: Mapped[int] = mapped_column(default=0)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    proxy: Mapped[Proxy | None] = relationship(back_populates="sessions")

    def __repr__(self) -> str:
        return f"<TelegramSession phone={self.phone} status={self.status} role={self.role}>"
