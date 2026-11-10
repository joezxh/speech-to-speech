from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, utcnow


class ParamInstance(Base):
    """注册表：seed 幂等键是 instance_id；enabled/drain_requested 是运维开关，
    seed 永远不覆盖（spec §7）。"""

    __tablename__ = "param_instance"
    __table_args__ = (UniqueConstraint("instance_id", name="uq_param_instance_instance_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    instance_id: Mapped[str] = mapped_column(String(64), nullable=False)
    base_url: Mapped[str] = mapped_column(String(255), nullable=False)
    weight: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # 声明容量：仅展示与偏差告警，永不参与分配（spec 决策 3）。
    max_sessions_hint: Mapped[int | None] = mapped_column(Integer, nullable=True)
    labels_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # 期望态落库，console 重启后 draining 保持（spec §6.2）。
    drain_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_by: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    # 集群归属（spec §2.2）：软关联 param_cluster.name，存量经 server_default 落 default。
    cluster_id: Mapped[str] = mapped_column(String(64), nullable=False, default="default", index=True)
