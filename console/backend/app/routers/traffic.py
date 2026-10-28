from __future__ import annotations

from fastapi import APIRouter, Depends

from app.config import allocator
from app.core.security import CurrentUser, require_user
from app.schemas.common import ok

router = APIRouter(prefix="/api/v1", tags=["traffic"])


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
            "unimplemented": ["session-stickiness", "canary-ratio", "routing-rules"],
        }
    )
