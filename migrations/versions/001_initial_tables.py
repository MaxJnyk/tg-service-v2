"""Initial tables: bot_accounts, proxies, telegram_sessions

Revision ID: 001
Revises: None
Create Date: 2026-04-08
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Proxies first (referenced by telegram_sessions)
    op.create_table(
        "proxies",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column("host", sa.String, nullable=False),
        sa.Column("port", sa.Integer, nullable=False),
        sa.Column("protocol", sa.String, server_default="socks5"),
        sa.Column("username", sa.String, nullable=True),
        sa.Column("password", sa.String, nullable=True),
        sa.Column("country_code", sa.String(2), nullable=True),
        sa.Column("is_active", sa.Boolean, server_default=sa.text("true")),
        sa.Column("response_time_ms", sa.Integer, nullable=True),
        sa.Column("fail_count", sa.Integer, server_default=sa.text("0")),
    )

    op.create_table(
        "bot_accounts",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column("bot_token", sa.String, nullable=False),
        sa.Column("name", sa.String, nullable=False),
        sa.Column("platform_id", UUID(as_uuid=False), nullable=True),
        sa.Column("is_active", sa.Boolean, server_default=sa.text("true")),
        sa.Column("fail_count", sa.Integer, server_default=sa.text("0")),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "telegram_sessions",
        sa.Column("id", UUID(as_uuid=False), primary_key=True),
        sa.Column("phone", sa.String, unique=True, nullable=False),
        sa.Column("session_string", sa.String, nullable=False),
        sa.Column("api_id", sa.Integer, nullable=False),
        sa.Column("api_hash", sa.String, nullable=False),
        sa.Column("device_info", sa.JSON, server_default=sa.text("'{}'::json")),
        sa.Column("proxy_id", UUID(as_uuid=False), sa.ForeignKey("proxies.id"), nullable=True),
        sa.Column("status", sa.String, server_default="active"),
        sa.Column("role", sa.String, server_default="scrape"),
        sa.Column("flood_wait_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fail_count", sa.Integer, server_default=sa.text("0")),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
    )

    # Indexes for common queries
    op.create_index("ix_bot_accounts_is_active", "bot_accounts", ["is_active"])
    op.create_index("ix_bot_accounts_platform_id", "bot_accounts", ["platform_id"])
    op.create_index("ix_telegram_sessions_status_role", "telegram_sessions", ["status", "role"])
    op.create_index("ix_proxies_is_active", "proxies", ["is_active"])


def downgrade() -> None:
    op.drop_table("telegram_sessions")
    op.drop_table("bot_accounts")
    op.drop_table("proxies")
