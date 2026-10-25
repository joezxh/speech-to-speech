from __future__ import annotations

from app.schemas.common import iso_utc

WINDOWS = {"1h": 3600, "6h": 21600, "24h": 86400, "7d": 604800}


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
