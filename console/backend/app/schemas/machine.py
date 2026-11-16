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

__all__ = [
    "AutoRegisterIn",
    "MachineCreate",
    "MachineUpdate",
    "RegisterTestIn",
    "WorkloadsPut",
]
