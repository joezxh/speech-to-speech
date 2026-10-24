from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class DraftPatchRequest(BaseModel):
    patch: dict[str, Any] = Field(min_length=1)
    baseVersion: int | None = None
