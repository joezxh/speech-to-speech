from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Request

from app.config import demo
from app.services import lb_service, metering_service

router = APIRouter(prefix="/api", tags=["demo"])


@router.post("/session")
async def session(request: Request):
    """向 LB 申请会话：授权，或一张排队票。未配 LB 时 404（防探测）。"""
    if not demo.lb_url:
        raise HTTPException(status_code=404, detail="Not found.")
    return await lb_service.start(request)


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
