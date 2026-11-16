from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, utcnow


class ParamRelease(Base):
    """发布流水线台账：build/staging 由外部 CI 执行，console 只记账（需求拍板）。

    与 param_version 的分工：那边存配置内容快照（yaml_text），这边存发布过程
    （阶段、灰度比例、节点、变更清单），用 profile_version 关联，不合并成一张表。
    """

    __tablename__ = "param_release"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    # 关联 param_version.version；CI 侧还没产出对应 profile 版本时为空。
    profile_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    cluster_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")
    stage: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    rollout_pct: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    nodes: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    changes: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    created_by: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
