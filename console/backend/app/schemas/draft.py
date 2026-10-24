from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class DraftPatchRequest(BaseModel):
    patch: dict[str, Any] = Field(min_length=1)
    baseVersion: int | None = None


class PublishRequest(BaseModel):
    baseVersion: int | None = None
    note: str = Field(default="", max_length=500)


class RollbackRequest(BaseModel):
    targetVersion: int
    note: str = Field(default="", max_length=500)
