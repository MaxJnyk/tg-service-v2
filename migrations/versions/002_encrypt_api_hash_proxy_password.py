"""Encrypt api_hash and proxy password fields.

Data migration: reads existing plaintext values, encrypts them with Fernet,
and writes them back. Idempotent — skips values that look already encrypted
(Fernet tokens start with 'gAAAAA').

Revision ID: 002
Revises: 001
Create Date: 2026-04-08
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_FERNET_PREFIX = "gAAAAA"


def _is_already_encrypted(value: str) -> bool:
    return value.startswith(_FERNET_PREFIX)


def upgrade() -> None:
    from src.core.security import encrypt

    conn = op.get_bind()

    # Encrypt telegram_sessions.api_hash
    rows = conn.execute(
        sa.text("SELECT id, api_hash FROM telegram_sessions")
    ).fetchall()
    for row in rows:
        if not _is_already_encrypted(row.api_hash):
            encrypted = encrypt(row.api_hash)
            conn.execute(
                sa.text("UPDATE telegram_sessions SET api_hash = :val WHERE id = :id"),
                {"val": encrypted, "id": row.id},
            )

    # Encrypt proxies.password
    rows = conn.execute(
        sa.text("SELECT id, password FROM proxies WHERE password IS NOT NULL")
    ).fetchall()
    for row in rows:
        if not _is_already_encrypted(row.password):
            encrypted = encrypt(row.password)
            conn.execute(
                sa.text("UPDATE proxies SET password = :val WHERE id = :id"),
                {"val": encrypted, "id": row.id},
            )


def downgrade() -> None:
    from src.core.security import decrypt

    conn = op.get_bind()

    # Decrypt telegram_sessions.api_hash back to plaintext
    rows = conn.execute(
        sa.text("SELECT id, api_hash FROM telegram_sessions")
    ).fetchall()
    for row in rows:
        if _is_already_encrypted(row.api_hash):
            plaintext = decrypt(row.api_hash)
            conn.execute(
                sa.text("UPDATE telegram_sessions SET api_hash = :val WHERE id = :id"),
                {"val": plaintext, "id": row.id},
            )

    # Decrypt proxies.password back to plaintext
    rows = conn.execute(
        sa.text("SELECT id, password FROM proxies WHERE password IS NOT NULL")
    ).fetchall()
    for row in rows:
        if _is_already_encrypted(row.password):
            plaintext = decrypt(row.password)
            conn.execute(
                sa.text("UPDATE proxies SET password = :val WHERE id = :id"),
                {"val": plaintext, "id": row.id},
            )
