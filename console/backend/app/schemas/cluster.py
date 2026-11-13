from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class ClusterCreate(BaseModel):
    """字段一律无 pydantic 约束：校验链在 cluster_service，失败才能被路由体的
    try/except 捕获并审计（RequestValidationError 不进路由体，spec §4.3）。"""

    model_config = ConfigDict(extra="forbid")

    name: str
    registry: str
    policy: str
    note: str = ""


class ClusterUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    registry: str
    policy: str
    note: str = ""