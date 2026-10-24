from __future__ import annotations

from pydantic import BaseModel, Field


class VoiceDuplicateRequest(BaseModel):
    """`POST /voices/{id}/duplicate` — the name is optional, A.18."""

    name: str | None = Field(default=None, max_length=64)
