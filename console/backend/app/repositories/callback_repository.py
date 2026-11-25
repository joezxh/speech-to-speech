"""callback_target / callback_delivery_log 数据访问（只做查询与落库）。"""
from __future__ import annotations

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.models.callbacks import CallbackDeliveryLog, CallbackTarget


class CallbackRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def list(self, page: int = 1, page_size: int = 50) -> tuple[list[CallbackTarget], int]:
        total = self.db.scalar(select(func.count()).select_from(CallbackTarget)) or 0
        rows = self.db.scalars(
            select(CallbackTarget).order_by(CallbackTarget.id.desc())
            .offset((page - 1) * page_size).limit(page_size)
        ).all()
        return list(rows), int(total)

    def get(self, target_id: int) -> CallbackTarget | None:
        return self.db.get(CallbackTarget, target_id)

    def create(self, **fields) -> CallbackTarget:
        row = CallbackTarget(**fields)
        self.db.add(row)
        self.db.commit()
        self.db.refresh(row)
        return row

    def update(self, target_id: int, **fields) -> CallbackTarget | None:
        row = self.get(target_id)
        if row is None:
            return None
        for key, value in fields.items():
            setattr(row, key, value)
        self.db.commit()
        self.db.refresh(row)
        return row

    def delete(self, target_id: int) -> bool:
        row = self.get(target_id)
        if row is None:
            return False
        self.db.delete(row)
        self.db.commit()
        return True

    def batch_set_enabled(self, ids: list[int], enabled: bool) -> int:
        result = self.db.execute(
            update(CallbackTarget).where(CallbackTarget.id.in_(ids))
            .values(enabled=enabled))
        self.db.commit()
        return int(result.rowcount or 0)

    def batch_delete(self, ids: list[int]) -> int:
        result = self.db.execute(delete(CallbackTarget).where(CallbackTarget.id.in_(ids)))
        self.db.commit()
        return int(result.rowcount or 0)

    def list_logs(self, *, target_id: int | None, status: str | None,
                  since=None, until=None, page: int = 1, page_size: int = 50):
        stmt = select(CallbackDeliveryLog).order_by(CallbackDeliveryLog.id.desc())
        count_stmt = select(func.count()).select_from(CallbackDeliveryLog)
        if target_id is not None:
            stmt = stmt.where(CallbackDeliveryLog.target_id == target_id)
            count_stmt = count_stmt.where(CallbackDeliveryLog.target_id == target_id)
        if status:
            stmt = stmt.where(CallbackDeliveryLog.status == status)
            count_stmt = count_stmt.where(CallbackDeliveryLog.status == status)
        total = self.db.scalar(count_stmt) or 0
        rows = self.db.scalars(stmt.offset((page - 1) * page_size).limit(page_size)).all()
        return list(rows), int(total)
