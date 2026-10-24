from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app.config import demo
from app.services import calls_service

router = APIRouter(prefix="/api", tags=["demo"])


@router.post("/calls")
async def calls(request: Request):
    """只转发到 env 钉死的地址：接受客户端目标就是开放代理（SSRF）。"""
    if not demo.pinned_url:
        raise HTTPException(status_code=404, detail="Not found.")
    return await calls_service.forward(
        calls_service.handshake_url(demo.pinned_url), await request.body(), keep_location=True
    )
