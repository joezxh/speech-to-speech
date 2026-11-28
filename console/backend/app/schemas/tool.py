"""tools 路由的请求模型（camelCase 契约，与原型弹窗字段一一对应）。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ToolParamIn(BaseModel):
    k: str = Field(default="", max_length=64)
    t: str = Field(default="string", max_length=16)
    req: bool = False


class ToolCreate(BaseModel):
    name: str = Field(default="", max_length=128)
    type: str = Field(default="http", max_length=32)
    description: str = Field(default="", max_length=512)
    endpoint: str = Field(default="", max_length=512)
    method: str = Field(default="GET", max_length=8)
    scope: str = Field(default="global", max_length=16)
    enabled: bool = True
    params: list[ToolParamIn] = Field(default_factory=list)
    config: dict = Field(default_factory=dict)


class ToolUpdate(BaseModel):
    name: str | None = Field(default=None, max_length=128)
    type: str | None = Field(default=None, max_length=32)
    description: str | None = Field(default=None, max_length=512)
    endpoint: str | None = Field(default=None, max_length=512)
    method: str | None = Field(default=None, max_length=8)
    scope: str | None = Field(default=None, max_length=16)
    enabled: bool | None = None
    params: list[ToolParamIn] | None = None
    config: dict | None = None


class ToolInvoke(BaseModel):
    arguments: dict = Field(default_factory=dict)
