from __future__ import annotations

from fastapi import APIRouter, Depends

from app.config import allocator
from app.core.permissions import require_permission
from app.core.security import CurrentUser, require_user
from app.deps import DbSession
from app.schemas.common import ok
from app.services import traffic_latency_service

router = APIRouter(prefix="/api/v1", tags=["traffic"])


@router.get("/traffic/latency-stats")
def latency_stats(
    db: DbSession,
    user: CurrentUser = Depends(require_permission("console:lb:query")),
    window: str = "1h",
):
    """P95 TTFT / 错误率 / top 错误实例 / 实例级 TTFT·RTF（turn_latency + instance_metric）。"""
    return ok(traffic_latency_service.latency_stats(db, window))


@router.get("/traffic/settings")
def get_traffic_settings(user: CurrentUser = Depends(require_user)):
    """Read-only allocator snapshot (spec §10.2). No write path, no DB, no audit.

    ``scheduling.configurable`` is False because the policy is hard-coded in
    ``allocator._candidates``; S3 flips it to a real enum without touching
    the frontend structure. ``unimplemented`` is declared here, not guessed
    client-side.
    """
    return ok(
        {
            "allocatorMode": allocator.mode,
            "consoleId": allocator.resolved_console_id,
            "seedConfigured": bool(allocator.seed_path.strip()),
            "probeIntervalS": allocator.probe_interval_s,
            "probeTimeoutS": allocator.probe_timeout_s,
            "failThreshold": allocator.fail_threshold,
            "recoverThreshold": allocator.recover_threshold,
            "grantTtlS": allocator.grant_ttl_s,
            "usageIntervalS": allocator.usage_interval_s,
            "metricRetentionDays": allocator.metric_retention_days,
            "queueEnabled": allocator.queue_enabled,
            "webrtcHangupEnabled": allocator.webrtc_hangup_enabled,
            "scheduling": {
                "policy": "least-in-use",
                "configurable": False,
                "tieBreaker": "weight-random",
            },
            # Task 17/18：会话粘性（param_lb_affinity）、金丝雀比例（share_pct）、
            # 路由规则（param_lb_rule）已全部落地，unimplemented 清空。
            "unimplemented": [],
        }
    )
