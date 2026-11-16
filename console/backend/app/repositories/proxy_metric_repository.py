from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.param_proxy_metric import ParamProxyMetric


def _as_aware(value: datetime | None) -> datetime | None:
    """SQLite round-trips `DateTime(timezone=True)` as a *naive* UTC value; Postgres
    returns it aware. 消费方拿它跟 utcnow() 比，所以这里归一化（同
    instance_metric_repository 的同名函数）。"""
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=UTC)


class ProxyMetricRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def insert_many(self, rows: list[dict]) -> int:
        prepared = []
        for row in rows:
            data = dict(row)
            data.setdefault("ok", 0)
            data.setdefault("fail_count", 0)
            data.setdefault("fail_reason", "")
            data.setdefault("duration_ms", 0)
            data.setdefault("observed_by", "")
            prepared.append(ParamProxyMetric(**data))
        self.session.add_all(prepared)
        self.session.commit()
        return len(prepared)

    def window(
        self,
        instance_id: str,
        *,
        since: datetime,
        service: str | None = None,
        observed_by: str | None = None,
    ) -> list[ParamProxyMetric]:
        stmt = (
            select(ParamProxyMetric)
            .where(
                ParamProxyMetric.instance_id == instance_id,
                ParamProxyMetric.observed_at >= since,
            )
            .order_by(ParamProxyMetric.observed_at.asc())
        )
        if service:
            stmt = stmt.where(ParamProxyMetric.service == service)
        if observed_by:
            stmt = stmt.where(ParamProxyMetric.observed_by == observed_by)
        return list(self.session.scalars(stmt))

    def latest_observed_at(self) -> datetime | None:
        return _as_aware(self.session.scalar(select(ParamProxyMetric.observed_at).order_by(ParamProxyMetric.observed_at.desc()).limit(1)))

    def prune_before(self, cutoff: datetime) -> int:
        result = self.session.execute(
            delete(ParamProxyMetric).where(ParamProxyMetric.observed_at < cutoff)
        )
        self.session.commit()
        return result.rowcount or 0
