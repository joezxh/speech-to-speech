"""machines 路由的请求模型（camelCase 契约，与 machine_service 共用类型）。"""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.services.machine_service import (
    AutoRegisterIn,
    MachineCreate,
    MachineUpdate,
    RegisterTestIn,
    WorkloadIn,
)


class WorkloadsPut(BaseModel):
    workloads: list[WorkloadIn]


class MachineDraftPut(BaseModel):
    """D4：机器草稿保存；base_version 来自 GET draft 的 version（乐观锁）。"""

    patch: dict[str, str]
    base_version: int = 0


class MachineDeployIn(BaseModel):
    """D6：push/rollback；非 canary 机器的 push 需 confirm_word == machine_id。"""

    mode: str = "push"
    rows: list[str] | None = None
    confirm_word: str = ""


class MachineCommandIn(BaseModel):
    """用户侧下发机器命令；serviceId 仅 health_check 使用（agent 侧按它探测）。"""

    kind: str = Field(min_length=1, max_length=32)
    serviceId: str = Field(default="", max_length=64)


__all__ = [
    "MachineCommandIn",
    "AutoRegisterIn",
    "MachineCreate",
    "MachineDeployIn",
    "MachineDraftPut",
    "MachineUpdate",
    "RegisterTestIn",
    "WorkloadsPut",
]
