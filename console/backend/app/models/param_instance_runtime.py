from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, utcnow


class ParamInstanceRuntime(Base):
    """实例运行时状态（spec 2026-11-17 §2.1）：巡检推导，跨副本共享。

    与 `param_instance` 的分工：那张表放**声明数据**（有哪些机器、地址、权重），
    这张表放**观测到的状态**（健康五态、槽位占用、能力指纹）。控制台重启后
    直接读到上次的状态，不必等首轮探测；多副本同时探测同一实例时读侧取最新一条。

    `reserved` 是本实例上的选台占位数（pending + held），选台时用它做原子判定，
    避免两个副本各自算余量导致超发（spec §2.2）。

    不建 FK：实例删除后历史仍可读，与 `param_instance_metric` 既有做法一致。
    """

    __tablename__ = "param_instance_runtime"
    __table_args__ = (UniqueConstraint("instance_id", name="uq_param_instance_runtime_instance_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    instance_id: Mapped[str] = mapped_column(String(64), nullable=False)
    # unknown / online / degraded / offline / draining
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="unknown")
    pool_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    in_use: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stuck: Mapped[int | None] = mapped_column(Integer, nullable=True)
    probe_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 能力指纹：派生状态（探测得到），与 `param_instance_metric` 的槽位口径分开存。
    capabilities: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    capability_issues: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    consecutive_failures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    consecutive_successes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_error: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    probe_history: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    # 本实例上的占位数（pending + held），选台的原子判定就用它。
    reserved: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    # 采集方标识；多副本同时探测时用于区分来源（读侧取 observed_at 最新的一条）。
    observed_by: Mapped[str] = mapped_column(String(64), nullable=False, default="")
