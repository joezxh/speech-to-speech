"""smart-settings 路由的请求模型（camelCase 契约）。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class SmartFetchIn(BaseModel):
    machineId: str = Field(min_length=1, max_length=64)


class SmartAnalyzeIn(BaseModel):
    machineId: str = Field(default="", max_length=64)
    fault: str = Field(min_length=1, max_length=2000)
    params: dict[str, str] = Field(default_factory=dict)
    logs: list[str] = Field(default_factory=list)
