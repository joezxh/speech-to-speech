"""templates 路由的请求模型（camelCase 契约，与原型弹窗字段一一对应）。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class TemplateFieldIn(BaseModel):
    """模板字段快照条目：key 为目录参数键（<stage>.<name>）或热更参数名。"""

    key: str = Field(min_length=1, max_length=128)
    value: str = Field(default="", max_length=512)
    patch: str = Field(default="", max_length=255)
    source: str = Field(default="", max_length=255)


class TemplateCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    effect: str = Field(default="runtime", max_length=16)
    platform: str = Field(default="gpu", max_length=16)
    status: str = Field(default="draft", max_length=16)
    scene: str = Field(default="", max_length=32)
    minVramGb: float | None = Field(default=None, ge=0)
    fields: list[TemplateFieldIn] = Field(default_factory=list)
    desc: str = Field(default="", max_length=512)


class TemplateUpdate(BaseModel):
    """部分更新：只取显式传入的字段（exclude_unset）。"""

    name: str | None = Field(default=None, min_length=1, max_length=128)
    effect: str | None = Field(default=None, max_length=16)
    platform: str | None = Field(default=None, max_length=16)
    status: str | None = Field(default=None, max_length=16)
    scene: str | None = Field(default=None, max_length=32)
    minVramGb: float | None = Field(default=None, ge=0)
    fields: list[TemplateFieldIn] | None = None
    desc: str | None = Field(default=None, max_length=512)
