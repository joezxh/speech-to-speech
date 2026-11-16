from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.common import iso_utc

WINDOWS = {"1h": 3600, "6h": 21600, "24h": 86400, "7d": 604800}


class HangupRequest(BaseModel):
    # 就是实例侧的 call_id：WebRTC 会话在 /v1/realtime/calls 里以它寻址。
    session_id: str


class InstanceCreate(BaseModel):
    """在线纳管一台实例（spec 2026-11-17 §5.4）。

    以前只能改 seed 文件再重启；现在直接写库，巡检下一轮就会探它。
    """

    instance_id: str = Field(min_length=1, max_length=64)
    base_url: str = Field(min_length=1, max_length=255)
    weight: int = Field(default=1, ge=0, le=1000)
    max_sessions_hint: int | None = Field(default=None, ge=0)
    labels: dict[str, str] = Field(default_factory=dict)
    cluster_id: str = Field(default="default", max_length=64)


def metric_point(row) -> dict:
    return {
        "observedAt": iso_utc(row.observed_at),
        "observedBy": row.observed_by,
        "kind": row.kind,
        "status": row.status,
        "size": row.size,
        "inUse": row.in_use,
        "free": row.free,
        "stuck": row.stuck,
        "probeMs": row.probe_ms,
        "allocOk": row.alloc_ok,
        "allocFailNoInstance": row.alloc_fail_no_instance,
        "allocFailInstance503": row.alloc_fail_instance_503,
        "evictCount": row.evict_count,
        "recoverCount": row.recover_count,
    }


def proxy_metric_point(row) -> dict:
    """数据面代理采样点（spec §7）。与 metric_point 分开：两张表的列语义不同。"""
    return {
        "observedAt": iso_utc(row.observed_at),
        "observedBy": row.observed_by,
        "service": row.service,
        "ok": row.ok,
        "failCount": row.fail_count,
        "failReason": row.fail_reason,
        "durationMs": row.duration_ms,
    }
