"""配置读写接口的请求模型（spec 2026-11-17 §6.1）。

值统一用 `Any` 承载：类型转换与取值域校验在服务层按登记表做，
前端不必把 int / bool 转成字符串再发过来。
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ConfigUpdateRequest(BaseModel):
    """批量写配置：键必须是登记在册的 `section.attr`。"""

    values: dict[str, Any] = Field(default_factory=dict)  
