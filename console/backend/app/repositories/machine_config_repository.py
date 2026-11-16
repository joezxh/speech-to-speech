"""机器实际生效配置（A3 report 的落点，漂移源；spec 2026-11-17 §7.1）。

每机每键一行（uq_param_machine_config_key），report 逐键 upsert。
密钥类键在进本仓储前已被 agent_config_service.secret_keys_filtered 过滤。
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.base import utcnow
from app.models.machine_config import ParamMachineConfig


class MachineConfigRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def upsert_report(self, machine_id: str, values: dict, config_version: int) -> int:
        """逐键 upsert；返回落库键数。值统一按字符串存（actual_value 列口径）。"""
        for key, value in values.items():
            row = self.session.scalar(
                select(ParamMachineConfig).where(
                    ParamMachineConfig.machine_id == machine_id,
                    ParamMachineConfig.param_key == key,
                )
            )
            if row is None:
                row = ParamMachineConfig(machine_id=machine_id, param_key=key)
                self.session.add(row)
            row.actual_value = str(value)
            row.config_version = config_version
            row.observed_at = utcnow()
            row.reported_by = "agent"
        self.session.commit()
        return len(values)
