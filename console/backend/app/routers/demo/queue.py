from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app.config import demo
from app.services import lb_service

router = APIRouter(prefix="/api", tags=["demo"])


@router.get("/queue/{queue_id}")
async def status(queue_id: str, request: Request):
    """轮询等待票：位次，或排到头部时拿到的授权。"""
    if not demo.lb_url:
        raise HTTPException(status_code=404, detail="Not found.")
    return await lb_service.poll(request, queue_id)


@router.delete("/queue/{queue_id}")
async def leave(queue_id: str, request: Request):
    """「离开队列」按钮（真 fetch）。"""
    if not demo.lb_url:
        raise HTTPException(status_code=404, detail="Not found.")
    await lb_service.leave(queue_id, request)
    return {"ok": True}


@router.post("/queue/end")
async def end(request: Request):
    """拆页时用 navigator.sendBeacon 离开队列（只能 POST）。体 `{queueId}`。"""
    if not demo.lb_url:
        raise HTTPException(status_code=404, detail="Not found.")
    queue_id = await lb_service.body_field(request, "queueId")
    if queue_id:
        await lb_service.leave(queue_id, request)
    return {"ok": True}
