"""机器声明数据的读写（spec 2026-11-17 §7.1：机器是一等公民）。

全用软关联、不建 FK：机器删除时连带清掉 workload/draft/config 行，
token_metric 保留历史（与 param_instance_metric「实例删除后历史仍可读」同口径）。
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.base import utcnow
from app.models.machine import ParamMachine, ParamMachineWorkload
from app.models.machine_config import ParamMachineConfig, ParamMachineDraft


class MachineRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list(self, cluster: str | None = None) -> list[ParamMachine]:
        stmt = select(ParamMachine).order_by(ParamMachine.machine_id)
        if cluster is not None:
            stmt = stmt.where(ParamMachine.cluster_id == cluster)
        return list(self.session.scalars(stmt))

    def get(self, machine_id: str) -> ParamMachine | None:
        return self.session.scalar(select(ParamMachine).where(ParamMachine.machine_id == machine_id))

    def create(self, *, row: ParamMachine) -> ParamMachine:
        self.session.add(row)
        self.session.commit()
        self.session.refresh(row)
        return row

    def delete(self, machine_id: str) -> bool:
        row = self.get(machine_id)
        if row is None:
            return False
        # 连带清理：workload（清单）与 draft/config（机器维度的配置面），
        # token_metric 保留历史。逐个 delete 而非批量 UPDATE：行数很小。
        for model in (ParamMachineWorkload, ParamMachineDraft, ParamMachineConfig):
            for child in self.session.scalars(select(model).where(model.machine_id == machine_id)):
                self.session.delete(child)
        self.session.delete(row)
        self.session.commit()
        return True

    # ---- 负载清单（全量覆盖） -------------------------------------------

    def list_workloads(self, machine_id: str) -> list[ParamMachineWorkload]:
        return list(
            self.session.scalars(
                select(ParamMachineWorkload)
                .where(ParamMachineWorkload.machine_id == machine_id)
                .order_by(ParamMachineWorkload.id)
            )
        )

    def replace_workloads(self, machine_id: str, items: list[dict]) -> list[ParamMachineWorkload]:
        """全量覆盖：按 (kind, port) 对齐——匹配的行更新，其余旧行删除、新条目插入。"""
        existing = self.list_workloads(machine_id)
        by_key: dict[tuple[str, int | None], ParamMachineWorkload] = {
            (row.kind, row.port): row for row in existing
        }
        kept: list[ParamMachineWorkload] = []
        for item in items:
            key = (item["kind"], item.get("port"))
            row = by_key.pop(key, None)
            if row is None:
                row = ParamMachineWorkload(machine_id=machine_id)
                self.session.add(row)
            for field, value in item.items():
                setattr(row, field, value)
            row.updated_at = utcnow()
            kept.append(row)
        for stale in by_key.values():
            self.session.delete(stale)
        self.session.commit()
        for row in kept:
            self.session.refresh(row)
        return kept
