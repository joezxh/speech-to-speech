"""LB 规则的请求模型（camelCase 契约由路由层转换，此处与 service 对齐）。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class LbRuleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    priority: int
    match_type: str = Field(default="default", max_length=16)
    match_value: str = Field(default="", max_length=255)
    target_kind: str = Field(default="instance", max_length=16)
    target_value: str = Field(default="", max_length=255)
    share_pct: int | None = None
    sticky_ttl_s: int | None = None
    enabled: bool = True


class LbRuleUpdate(BaseModel):
    name: str | None = None
    priority: int | None = None
    match_type: str | None = None
    match_value: str | None = None
    target_kind: str | None = None
    target_value: str | None = None
    share_pct: int | None = None
    sticky_ttl_s: int | None = None
    enabled: bool | None = None
