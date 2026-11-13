from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.base import utcnow
from app.models.param_cluster import ParamCluster


class ClusterRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_all(self) -> list[ParamCluster]:
        # ORDER BY id：default（seed 行）恒在最前，前端回落依赖这个顺序（spec §5.1）。
        return list(self.session.scalars(select(ParamCluster).order_by(ParamCluster.id)))

    def get_by_name(self, name: str) -> ParamCluster | None:
        return self.session.scalar(select(ParamCluster).where(ParamCluster.name == name))

    def count_registry_conflicts(self, registry: str, *, exclude_name: str = "") -> int:
        stmt = select(func.count()).select_from(ParamCluster).where(ParamCluster.registry == registry)
        if exclude_name:
            stmt = stmt.where(ParamCluster.name != exclude_name)
        return int(self.session.scalar(stmt) or 0)

    def create(self, *, name: str, registry: str, policy: str, note: str, updated_by: str) -> ParamCluster:
        row = ParamCluster(name=name, registry=registry, policy=policy, note=note, updated_by=updated_by)
        self.session.add(row)
        self.session.commit()
        self.session.refresh(row)
        return row

    def update(self, row: ParamCluster, *, registry: str, policy: str, note: str, updated_by: str) -> ParamCluster:
        # name 永不变更（spec §4.1：编辑态名称禁用，PUT body 无 name）。
        row.registry, row.policy, row.note = registry, policy, note
        row.updated_by, row.updated_at = updated_by, utcnow()
        self.session.commit()
        self.session.refresh(row)
        return row

    def delete(self, row: ParamCluster) -> None:
        self.session.delete(row)
        self.session.commit()