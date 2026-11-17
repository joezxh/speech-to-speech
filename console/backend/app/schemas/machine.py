"""machines 路由的请求模型（camelCase 契约，与 machine_service 共用类型）。"""

from __future__ import annotations

from pydantic import BaseModel

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

__all__ = [
    "AutoRegisterIn",
    "MachineCreate",
    "MachineDeployIn",
    "MachineDraftPut",
    "MachineUpdate",
    "RegisterTestIn",
    "WorkloadsPut",
]
