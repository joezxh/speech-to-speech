from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.models.param_instance import ParamInstance
from app.models.param_instance_metric import ParamInstanceMetric

_COUNT_COLUMNS = ("alloc_ok", "alloc_fail_no_instance", "alloc_fail_instance_503", "evict_count", "recover_count")


def _as_aware(value: datetime | None) -> datetime | None:
    """SQLite round-trips `DateTime(timezone=True)` as a *naive* UTC value; Postgres
    returns it aware. Consumers compare against `utcnow()`, so normalize here and
    never let a naive value leak out (same idiom as `schemas/common.py:iso_utc`)."""
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=UTC)


class InstanceMetricRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def insert_many(self, rows: list[dict]) -> int:
        prepared = []
        for row in rows:
            data = dict(row)
            for column in _COUNT_COLUMNS:
                data.setdefault(column, 0)
            prepared.append(ParamInstanceMetric(**data))
        self.session.add_all(prepared)
        self.session.commit()
        return len(prepared)

    def window(self, instance_id: str, *, since: datetime, observed_by: str | None = None) -> list[ParamInstanceMetric]:
        stmt = (
            select(ParamInstanceMetric)
            .where(ParamInstanceMetric.instance_id == instance_id, ParamInstanceMetric.observed_at >= since)
            .order_by(ParamInstanceMetric.observed_at.asc())
        )
        if observed_by:
            stmt = stmt.where(ParamInstanceMetric.observed_by == observed_by)
        return list(self.session.scalars(stmt))

    def latest_observed_at(self) -> datetime | None:
        return _as_aware(self.session.scalar(select(func.max(ParamInstanceMetric.observed_at))))

    def prune_before(self, cutoff: datetime) -> int:
        result = self.session.execute(delete(ParamInstanceMetric).where(ParamInstanceMetric.observed_at < cutoff))
        self.session.commit()
        return result.rowcount or 0

    def alloc_window_by_cluster(self, cluster_id: str | None, *, since: datetime) -> list[dict]:
        """窗口内按实例聚合的分配计数器（增量行求和，spec §4.4 前提：metric 落的是
        采样 tick 间 delta，非累计值，窗口求和成立）。cluster_id=None = 全部集群。"""
        stmt = (
            select(
                ParamInstanceMetric.instance_id,
                func.sum(ParamInstanceMetric.alloc_ok).label("ok"),
                func.sum(ParamInstanceMetric.alloc_fail_instance_503).label("fail_503"),
                func.sum(ParamInstanceMetric.alloc_fail_no_instance).label("fail_none"),
            )
            .where(ParamInstanceMetric.observed_at >= since, ParamInstanceMetric.kind == "sample")
            .group_by(ParamInstanceMetric.instance_id)
        )
        if cluster_id is not None:
            stmt = stmt.join(
                ParamInstance, ParamInstance.instance_id == ParamInstanceMetric.instance_id
            ).where(ParamInstance.cluster_id == cluster_id)
        return [
            {
                "instance_id": r.instance_id,
                "ok": int(r.ok or 0),
                "fail_503": int(r.fail_503 or 0),
                "fail_none": int(r.fail_none or 0),
            }
            for r in self.session.execute(stmt)
        ]
