"""
Pydantic-схемы для Kafka-сообщений.

Должны быть совместимы с tad-backend (TaskRequestSchema, TaskResultSchema).
Ничего тут не менять без согласования с бекендом БЛЕАТЬ!!!
"""

import re
from typing import Any
from uuid import UUID

from pydantic import BaseModel, field_validator, model_validator

_RESULT_TOPIC_RE = re.compile(r"^tad_[a-z_]+_result$")


def _is_invite_url(url: str) -> str | None:
    """Проверить, является ли URL invite-ссылкой. Вернуть hash или None."""
    if not url:
        return None
    match = re.search(r"(?:\+|joinchat/)([A-Za-z0-9_-]+)$", url)
    if match:
        return match.group(1)
    return None


class PlatformSchema(BaseModel):
    """Площадка из payload tad-backend (парсинг, постинг).

    Вспомогательные свойства:
      .username: извлекает из url (например, "t.me/channel" → "channel")
      .invite_hash: извлекает из invite-ссылки (например, "+ABcDeF123")
    """
    id: UUID | None = None
    url: str | None = None
    invite_link: str | None = None
    internal_id: str | None = None

    @property
    def username(self) -> str | None:
        if self.url:
            return self.url.strip("/").split("/")[-1]
        return None

    @property
    def ausername(self) -> str | None:
        if self.url:
            return "@" + self.url.strip("/").split("/")[-1]
        return None

    @property
    def invite_hash(self) -> str | None:
        if self.invite_link:
            return _is_invite_url(self.invite_link)
        return None

    @model_validator(mode="before")
    @classmethod
    def swap_invite_link(cls, values: dict[str, Any]) -> dict[str, Any]:
        url = values.get("url")
        if url and _is_invite_url(url):
            values["url"] = None
            values["invite_link"] = url
        return values


class PayloadSchema(BaseModel):
    platform: PlatformSchema


class TaskRequestSchema(BaseModel):
    """Входящая задача от tad-backend через Kafka."""
    request_id: str | UUID
    callback_task_name: str | None = None
    result_topic: str | None = None
    payload: Any | None = None

    @field_validator("result_topic")
    @classmethod
    def validate_result_topic(cls, v: str | None) -> str | None:
        if v is not None and not _RESULT_TOPIC_RE.match(v):
            raise ValueError(f"result_topic must match tad_*_result pattern, got: {v!r}")
        return v


class TaskResultSchema(BaseModel):
    """Результат, отправляемый обратно в tad-backend через Kafka."""
    request_id: str | UUID
    callback_task_name: str | None = None
    request_payload: Any | None = None
    error: str | None = None
    payload: Any | None = None
