"""选台占位租约的读写（spec 2026-11-17 §2.1 / §3.2）。

租约键是控制台自己生成的 uuid（`res_key`），不是上游 session_id——
"预留 → 会话"始终是同一把 key，占位不会因为换台而漏成两把。

时间一律**墙钟**（`expires_at`）：内存版用 monotonic 是为了躲机器间时钟偏差，
但跨进程共享就必须有一个共同的时间基准（spec §3.3）。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models.param_allocator_lease import ParamAllocatorLease

PENDING = "pending"
HELD = "held"


class AllocatorLeaseRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def get(self, lease_key: str) -> ParamAllocatorLease | None:
        return self.session.get(ParamAllocatorLease, lease_key)

    def insert(
        self,
        *,
        lease_key: str,
        instance_id: str,
        state: str = PENDING,
        expires_at: datetime | None = None,
        console_id: str = "",
        commit: bool = True,
    ) -> ParamAllocatorLease:
        row = ParamAllocatorLease(
            lease_key=lease_key,
            instance_id=instance_id,
            state=state,
            expires_at=expires_at,
            console_id=console_id,
        )
        self.session.add(row)
        if commit:
            self.session.commit()
            self.session.refresh(row)
        return row

    def mark_held(self, lease_key: str, instance_id: str, *, commit: bool = True) -> bool:
        """预留 → 会话期占位：不再靠 TTL 回收，随会话结束 release。"""
        row = self.get(lease_key)
        if row is None:
            return False
        row.state = HELD
        row.instance_id = instance_id
        row.expires_at = None
        if commit:
            self.session.commit()
        return True

    def delete(self, lease_key: str, *, commit: bool = True) -> ParamAllocatorLease | None:
        """删掉一条租约，返回删掉的那行（调用方要按 instance_id 把 reserved 减回去）。"""
        row = self.get(lease_key)
        if row is None:
            return None
        self.session.delete(row)
        if commit:
            self.session.commit()
        return row

    def expired_pending(self, now: datetime, *, commit: bool = True) -> list[ParamAllocatorLease]:
        """到期仍未连接的预留（墙钟判定）。"""
        rows = list(
            self.session.scalars(
                select(ParamAllocatorLease).where(
                    ParamAllocatorLease.state == PENDING,
                    ParamAllocatorLease.expires_at.is_not(None),
                    ParamAllocatorLease.expires_at < now,
                )
            )
        )
        for row in rows:
            self.session.delete(row)
        if commit and rows:
            self.session.commit()
        return rows

    def count(self, *, instance_id: str | None = None, state: str | None = None, console_id: str | None = None) -> int:
        stmt = select(func.count()).select_from(ParamAllocatorLease)
        if instance_id is not None:
            stmt = stmt.where(ParamAllocatorLease.instance_id == instance_id)
        if state is not None:
            stmt = stmt.where(ParamAllocatorLease.state == state)
        if console_id is not None:
            stmt = stmt.where(ParamAllocatorLease.console_id == console_id)
        return int(self.session.scalar(stmt) or 0)

    def delete_by_instance(self, instance_id: str, *, commit: bool = True) -> int:
        """摘掉实例时清掉它的租约（否则占位会一直挂着）。"""
        result = self.session.execute(
            delete(ParamAllocatorLease).where(ParamAllocatorLease.instance_id == instance_id)
        )
        if commit:
            self.session.commit()
        return int(result.rowcount or 0)  
