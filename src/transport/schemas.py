"""
Kafka message schemas — compatible with tad-backend's tg_messenger_client.

These are intentional copies of:
  tad-backend/app/src/tg_messenger_client/tg_messenger_client/schemas.py

We maintain our own copy to avoid git submodule dependency.
Schema compatibility is validated by integration tests.
"""

import re
from functools import cached_property
from typing import Any
from uuid import UUID

from pydantic import BaseModel, model_validator


def _is_invite_url(url: str) -> str | None:
    """Extract invite hash from Telegram invite URL."""
    if not url:
        return None
    match = re.search(r"(?:\+|joinchat/)([A-Za-z0-9_-]+)$", url)
    if match:
        return match.group(1)
    return None


class PlatformSchema(BaseModel):
    id: UUID | None = None
    url: str | None = None
    invite_link: str | None = None
    internal_id: str | None = None

    @cached_property
    def username(self) -> str | None:
        if self.url:
            return self.url.strip("/").split("/")[-1]
        return None

    @cached_property
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
    request_id: str | UUID
    callback_task_name: str | None = None
    result_topic: str | None = None
    payload: Any | None = None


class TaskResultSchema(BaseModel):
    request_id: str | UUID
    callback_task_name: str | None = None
    request_payload: Any | None = None
    error: str | None = None
    payload: Any | None = None
