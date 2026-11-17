"""agent 面协议模型（spec 2026-11-17 §5.2）。

与前端契约不同：agent 协议是 snake_case（对齐设计草案的 JSON 形状），
machine token 鉴权在服务层按 token 映射 machine_id（§5.4）。
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class AgentMachineIdentity(BaseModel):
    machine_id: str = Field(min_length=1, max_length=64)
    addr: str = Field(default="", max_length=255)
    gpu: str = Field(default="", max_length=64)
    gpu_total_gb: float | None = Field(default=None, ge=0)
    role: str = Field(default="agent", max_length=16)
    uptime_s: int | None = Field(default=None, ge=0)
    # 节点资源与 pipeline 版本（agent 真源；采集失败 = None，不编造）。
    version: str = Field(default="", max_length=64)
    gpu_util_pct: int | None = Field(default=None, ge=0, le=100)
    cpu_pct: float | None = Field(default=None, ge=0, le=100)
    load_avg: list[float] = Field(default_factory=list)
    mem_total_gb: float | None = Field(default=None, ge=0)
    mem_used_gb: float | None = Field(default=None, ge=0)
    mem_pct: float | None = Field(default=None, ge=0, le=100)
    gpu_mem_used_gb: float | None = Field(default=None, ge=0)
    gpu_mem_total_gb: float | None = Field(default=None, ge=0)
    pipeline_vram_gb: float | None = Field(default=None, ge=0)
    collected_at: str = Field(default="", max_length=40)


class AgentLogBatchIn(BaseModel):
    """容器日志批次：agent 已脱敏且有界，console 再收口一次。"""

    source: str = Field(default="stdout", max_length=16)
    lines: list[str] = Field(default_factory=list)


class AgentLogsIn(BaseModel):
    logs: list[AgentLogBatchIn] = Field(default_factory=list)


class AgentWorkload(BaseModel):
    """心跳负载条目：listen/public_addr 是实例绑定的唯一依据（§7.1）。"""

    kind: str = Field(default="pipeline", max_length=16)
    engine: str = Field(default="", max_length=64)
    model: str = Field(default="", max_length=128)
    port: int | None = Field(default=None, ge=0, le=65535)
    vram_gb: float | None = Field(default=None, ge=0)
    health_path: str = Field(default="", max_length=255)
    health_interval_s: int = Field(default=30, ge=1)
    listen: str = Field(default="", max_length=64)
    public_addr: str = Field(default="", max_length=64)
    note: str = Field(default="", max_length=255)
    # agent 从 pipeline 生效配置采集的模型与全部参数（密钥已掩码）。
    params: dict = Field(default_factory=dict)


class AgentRegisterIn(BaseModel):
    register_code: str = Field(min_length=1, max_length=128)
    machine: AgentMachineIdentity
    workloads: list[AgentWorkload] = Field(default_factory=list)


class HeartbeatIn(BaseModel):
    protocol_version: int = 1
    agent_version: str = Field(default="", max_length=64)
    machine: AgentMachineIdentity
    capabilities: list[str] = Field(default_factory=list)
    workloads: list[AgentWorkload] = Field(default_factory=list)
    runtime: dict = Field(default_factory=dict)
    # token 窗口增量（§5.2 草案的 tokens{}）：本任务暂存内存，Task 14 接表。
    tokens: dict = Field(default_factory=dict)


class AgentConfigReportIn(BaseModel):
    """A3：回报本机实际生效的配置键值（这份 values 就是漂移判定的实际值）。"""

    config_version: int
    applied_at: str = ""
    values: dict[str, str] = Field(default_factory=dict)


class AgentConfigAckIn(BaseModel):
    """A4：目标配置落地结果；ok=false 时该版本不留下发快照。"""

    config_version: int
    ok: bool
    error: str | None = None


class AgentTurnLatencyIn(BaseModel):
    """A5：逐轮 TURN_LATENCY 行上报（logged_at 为行内时间戳，ISO 字符串）。"""

    rows: list[dict] = Field(default_factory=list)


class AgentCommandReportIn(BaseModel):
    """机器命令回执：result 是真实执行/探测结果，不缓存伪造值。"""

    ok: bool
    result: dict = Field(default_factory=dict)
    error: str = Field(default="", max_length=512)


class AgentDrainIn(BaseModel):
    """agent 执行排空/恢复：只作用于 token 所指机器绑定的实例。"""

    drain: bool
