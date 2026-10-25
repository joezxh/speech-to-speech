"""Registry writes are seed-idempotent; runtime state never touches this table
(spec §5.1: DB 为真相源，运行时状态驻留内存)。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.base import utcnow
from app.models.param_instance import ParamInstance


class InstanceRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_all(self) -> list[ParamInstance]:
        return list(self.session.scalars(select(ParamInstance).order_by(ParamInstance.instance_id)))

    def get_by_instance_id(self, instance_id: str) -> ParamInstance | None:
        return self.session.scalar(select(ParamInstance).where(ParamInstance.instance_id == instance_id))

    def upsert_seed(
        self,
        *,
        instance_id: str,
        base_url: str,
        weight: int,
        max_sessions_hint: int | None,
        labels: dict,
        updated_by: str = "seed",
    ) -> tuple[ParamInstance, str]:
        """幂等 upsert（spec §7）。返回 (行, 告警名或 "")：新行告警为空；
        base_url 与 seed 冲突时返回 `instance_seed_conflict` 且以 DB 为准。
        永不覆盖 enabled / drain_requested——运维开关优先于 seed。"""
        row = self.get_by_instance_id(instance_id)
        alert = ""
        if row is None:
            row = ParamInstance(
                instance_id=instance_id,
                base_url=base_url,
                weight=weight,
                max_sessions_hint=max_sessions_hint,
                labels_json=labels,
                enabled=True,
                drain_requested=False,
                updated_by=updated_by,
            )
            self.session.add(row)
        elif row.base_url != base_url:
            alert = "instance_seed_conflict"
            # 其余字段仍同步，只有 base_url 以 DB 为准
            row.weight, row.max_sessions_hint, row.labels_json = weight, max_sessions_hint, labels
            row.updated_at = utcnow()
        else:
            row.base_url, row.weight = base_url, weight
            row.max_sessions_hint, row.labels_json = max_sessions_hint, labels
            row.updated_at = utcnow()
        row.updated_by = updated_by
        self.session.commit()
        self.session.refresh(row)
        return row, alert

    def set_drain(self, instance_id: str, *, drain: bool, updated_by: str) -> ParamInstance | None:
        row = self.get_by_instance_id(instance_id)
        if row is None:
            return None
        row.drain_requested, row.updated_by, row.updated_at = drain, updated_by, utcnow()
        self.session.commit()
        self.session.refresh(row)
        return row

    def set_enabled(self, instance_id: str, *, enabled: bool, updated_by: str) -> ParamInstance | None:
        row = self.get_by_instance_id(instance_id)
        if row is None:
            return None
        row.enabled, row.updated_by, row.updated_at = enabled, updated_by, utcnow()
        self.session.commit()
        self.session.refresh(row)
        return row
