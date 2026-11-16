from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from app.config import console, demo
from app.services import calls_service

router = APIRouter(prefix="/api", tags=["demo"])


@router.post("/calls")
async def calls(request: Request):
    """目标只来自服务端：proxy 模式按注册表选台，否则用 env 钉死的地址。

    接受客户端传目标就是开放代理（SSRF），所以目标只能来自 env 或服务端选台。
    """
    offer = await request.body()
    if console.lb_mode == "proxy":
        return await calls_service.forward_selected(offer, keep_location=True)
    if not demo.pinned_url:
        raise HTTPException(status_code=404, detail="Not found.")
    return await calls_service.forward(
        calls_service.handshake_url(demo.pinned_url), offer, keep_location=True
    )
