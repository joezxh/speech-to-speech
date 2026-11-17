"""发布台账请求/响应模型（Task 24，console 只记账）。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ReleaseCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    profile: str = Field(default="prod", max_length=64)
    artifactRef: str = Field(default="", max_length=512)


class StageResultIn(BaseModel):
    stage: str = Field(min_length=1, max_length=32)
    result: str = Field(default="ok", max_length=16)
    artifactRef: str = Field(default="", max_length=512)
    note: str = Field(default="", max_length=512)
    signature: str | None = None


class ReleaseOut(BaseModel):
    release_id: str
    version: str
    profile: str
    status: str
    stage: str
    created_by: str
    artifact_ref: str
    changes: list = Field(default_factory=list)
