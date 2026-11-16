"""实例运行时状态的读写（spec 2026-11-17 §2.1 / §3.2）。

两件事要注意：

1. **不碰 `reserved` 列**：那列归选台（allocator）所有，巡检只写观测值，
   否则巡检会把别的副本占住的槽位抹掉。
2. **占位判定用条件 UPDATE + rowcount**（不是行锁）：SQLite 没有
   `SELECT … FOR UPDATE`，一条带条件的 UPDATE 在两个方言下语义一致。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.models.param_instance_runtime import ParamInstanceRuntime


class InstanceRuntimeRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_all(self) -> list[ParamInstanceRuntime]:
        return list(self.session.scalars(select(ParamInstanceRuntime).order_by(ParamInstanceRuntime.instance_id)))

    def get(self, instance_id: str) -> ParamInstanceRuntime | None:
        return self.session.scalar(
            select(ParamInstanceRuntime).where(ParamInstanceRuntime.instance_id == instance_id)
        )

    def payloads(self) -> dict[str, dict[str, Any]]:
        """按实例 id 汇总运行时状态，供注册表恢复用。"""
        out: dict[str, dict[str, Any]] = {}
        for row in self.list_all():
            out[row.instance_id] = {
                "status": row.status,
                "pool_size": row.pool_size,
                "in_use": row.in_use,
                "stuck": row.stuck,
                "probe_ms": row.probe_ms,
                "capabilities": list(row.capabilities or []),
                "capability_issues": dict(row.capability_issues or {}),
                "consecutive_failures": row.consecutive_failures,
                "consecutive_successes": row.consecutive_successes,
                "last_error": row.last_error,
                "probe_history": list(row.probe_history or []),
                "reserved": row.reserved,
                "observed_at": row.observed_at,
                "observed_by": row.observed_by,
            }
        return out

    def upsert(self, *, instance_id: str, observed_by: str, **fields: Any) -> ParamInstanceRuntime:
        """写一条观测结果（不覆盖 `reserved`）。"""
        row = self.get(instance_id)
        if row is None:
            row = ParamInstanceRuntime(instance_id=instance_id, observed_by=observed_by, observed_at=datetime.now(UTC))
            self.session.add(row)
        for name, value in fields.items():
            setattr(row, name, value)
        row.observed_at = datetime.now(UTC)
        row.observed_by = observed_by
        self.session.commit()
        self.session.refresh(row)
        return row

    def delete(self, instance_id: str) -> bool:
        result = self.session.execute(
            delete(ParamInstanceRuntime).where(ParamInstanceRuntime.instance_id == instance_id)
        )
        self.session.commit()
        return bool(result.rowcount)

    # ── 占位（归选台所有）───────────────────────────────────────────────
    def reserve(self, instance_id: str, *, commit: bool = True) -> bool:
        """原子占一个槽位：条件 UPDATE + rowcount（spec §3.2）。

        条件是 `reserved < 剩余槽位`，剩余槽位 = size - in_use - stuck，
        用 COALESCE 处理 NULL（不可得 = 0 槽位，与内存版 `pool is None → False` 同义）。
        """
        free = (
            func.coalesce(ParamInstanceRuntime.pool_size, 0)
            - func.coalesce(ParamInstanceRuntime.in_use, 0)
            - func.coalesce(ParamInstanceRuntime.stuck, 0)
        )
        result = self.session.execute(
            update(ParamInstanceRuntime)
            .where(ParamInstanceRuntime.instance_id == instance_id)
            .where(ParamInstanceRuntime.reserved < free)
            .values(reserved=ParamInstanceRuntime.reserved + 1, observed_at=datetime.now(UTC))
        )
        if commit:
            self.session.commit()
        return bool(result.rowcount)

    def release_reserved(self, instance_id: str, *, commit: bool = True) -> None:
        """释放一个槽位（不会把计数压到负数）。"""
        self.session.execute(
            update(ParamInstanceRuntime)
            .where(ParamInstanceRuntime.instance_id == instance_id)
            .where(ParamInstanceRuntime.reserved > 0)
            .values(reserved=ParamInstanceRuntime.reserved - 1, observed_at=datetime.now(UTC))
        )
        if commit:
            self.session.commit()

    def reserved_count(self, instance_id: str) -> int:
        row = self.get(instance_id)
        return int(row.reserved or 0) if row is not None else 0  
