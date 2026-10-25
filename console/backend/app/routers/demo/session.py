from __future__ import annotations

import asyncio
import time
import uuid

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from app.config import allocator as allocator_settings
from app.config import demo
from app.services import allocator, identity_service, instance_monitor, lb_service, metering_service

router = APIRouter(prefix="/api", tags=["demo"])

GRANT_DEDUPE_WINDOW_S = 10  # spec §8.5：cookie + 10s 时间桶


def _local_mode_on() -> bool:
    if allocator_settings.mode != "local":
        return False
    # 注册表里有“在线/降级”的机器就走本地分配，哪怕余量为 0：满编时的正确
    # 答复是 503 at_capacity（spec §8.4），404 只属于“根本没配注册表”的现状。
    return any(
        state.enabled and state.status in ("online", "degraded")
        for state in instance_monitor.registry.snapshot().values()
    )


def _dedupe_key(request: Request) -> str:
    rid = request.headers.get("X-Request-Id", "").strip()
    if rid:
        return f"h:{rid}"
    anon = request.cookies.get(identity_service.ANON_COOKIE, "")
    bucket = int(time.monotonic() // GRANT_DEDUPE_WINDOW_S)
    return f"c:{anon}:{bucket}"


@router.post("/session")
async def session(request: Request):
    """向 LB 申请会话：授权，或一张排队票。未配 LB 且未开本地分配时 404（防探测）。"""
    if demo.lb_url:
        return await lb_service.start(request)  # 现有转发逐字不变（spec §8.1）
    if not _local_mode_on():
        raise HTTPException(status_code=404, detail="Not found.")  # 空注册表回现状（spec §15 P1.4）

    reason = identity_service.oauth_login_required_reason(request)
    if reason:
        return lb_service.login_required(reason)
    tier, keys, set_cookie = identity_service.resolve_identity(request)
    tracked = lb_service.tracked_for(tier)
    if tracked:  # 预算已没了就别占实例槽位（与 lb_service.start 同序）
        left = await asyncio.to_thread(metering_service.remaining, keys, tier)
        if left is not None and left <= 0:
            return lb_service.spent(tier, set_cookie)

    key = _dedupe_key(request)
    if allocator.store.begin_once(key, GRANT_DEDUPE_WINDOW_S) == "deduped":
        hit = allocator.store.grant_for(key)
        if hit:
            response = JSONResponse(hit)  # 已 finalize 的同一个 payload，不重复占位/不重复预留
            if set_cookie:
                identity_service.set_anon_cookie(response, set_cookie)
            return response
    grant = await allocator.allocate(str(uuid.uuid4()))
    if grant is None:
        response = JSONResponse({"state": "at_capacity"}, status_code=503)
        if set_cookie:
            identity_service.set_anon_cookie(response, set_cookie)
        return response
    data = dict(grant)
    response = await lb_service.finalize(data, keys, tier, tracked, set_cookie)
    allocator.store.remember_grant(key, data)  # 落盘的是 finalize 后的完整体
    return response


@router.post("/session/heartbeat")
async def heartbeat(request: Request):
    """续期。`expired: true` 时前端必须拆会话。"""
    if not demo.limiter_enabled:
        raise HTTPException(status_code=404, detail="Not found.")
    session_id = await lb_service.body_field(request, "sessionId")
    alive = bool(session_id) and await asyncio.to_thread(metering_service.heartbeat, session_id)
    return {"expired": not alive}


@router.post("/session/end")
async def end(request: Request):
    """按真实时长结算并退回未用块。走 sendBeacon，所以必须无条件成功。"""
    if not demo.limiter_enabled:
        raise HTTPException(status_code=404, detail="Not found.")
    session_id = await lb_service.body_field(request, "sessionId")
    if session_id:
        await asyncio.to_thread(metering_service.end, session_id)
    return {"ok": True}
