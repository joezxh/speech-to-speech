from __future__ import annotations

from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, utcnow


class ParamMachine(Base):
    """机器实体（spec §7.1 的一等公民）：实例从 host 派生改为挂在机器下。

    token_hash / register_code_hash 存 sha256，明文只出现一次（下发即丢弃）。
    两者都可空且唯一：建挡后、注册前只有注册码哈希；注册成功后补 token 哈希。
    不建 FK：cluster_id 是软关联，与 param_instance.cluster_id 既有做法一致。
    """

    __tablename__ = "param_machine"
    __table_args__ = (
        UniqueConstraint("machine_id", name="uq_param_machine_machine_id"),
        UniqueConstraint("token_hash", name="uq_param_machine_token_hash"),
        UniqueConstraint("register_code_hash", name="uq_param_machine_register_code_hash"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    machine_id: Mapped[str] = mapped_column(String(64), nullable=False)
    cluster_id: Mapped[str] = mapped_column(String(64), nullable=False, default="", index=True)
    # 空 = 回落 param_cluster.baseline_profile（§7.2.3 D1）。
    profile: Mapped[str | None] = mapped_column(String(64), nullable=True)
    addr: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    role: Mapped[str] = mapped_column(String(16), nullable=False, default="agent")
    gpu: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    gpu_total_gb: Mapped[float | None] = mapped_column(Float, nullable=True)
    version: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    # 节点资源与部署参数：agent 心跳上报，采集失败为空（不编数据）。
    gpu_util_pct: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cpu_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    load_avg: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    mem_total_gb: Mapped[float | None] = mapped_column(Float, nullable=True)
    mem_used_gb: Mapped[float | None] = mapped_column(Float, nullable=True)
    mem_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    gpu_mem_used_gb: Mapped[float | None] = mapped_column(Float, nullable=True)
    gpu_mem_total_gb: Mapped[float | None] = mapped_column(Float, nullable=True)
    pipeline_vram_gb: Mapped[float | None] = mapped_column(Float, nullable=True)
    collected_at: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    deployment_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="pending_register")
    registry_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="manual")
    agent_version: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    protocol_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    agent_caps: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    register_code_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    updated_by: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )


class ParamMachineWorkload(Base):
    """机器上的负载声明（心跳清单的全量覆盖写，upsert 键 = machine_id + kind + port）。"""

    __tablename__ = "param_machine_workload"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    machine_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="pipeline")
    engine: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    model: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    port: Mapped[int | None] = mapped_column(Integer, nullable=True)
    listen_addr: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    public_addr: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    vram_gb: Mapped[float | None] = mapped_column(Float, nullable=True)
    health_path: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    health_interval_s: Mapped[int] = mapped_column(Integer, nullable=False, default=30)
    note: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    # agent 从生效配置采集的 pipeline 模型与全部参数（密钥已掩码）。
    params_json: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )
