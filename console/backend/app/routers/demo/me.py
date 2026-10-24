from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from app.config import demo
from app.services import identity_service, metering_service

router = APIRouter(prefix="/api", tags=["demo"])


@router.get("/me")
def get_me(request: Request):
    """登录态、档位、今日剩余额度；未启用计量时只回 `{"enabled": false}`。

    写成同步函数：`resolve_tier` 会打一次 whoami-v2（带缓存），放进线程池
    才不堵事件循环；`remaining()` 也是阻塞的 sqlite 读。
    """
    if not demo.limiter_enabled:
        return {"enabled": False}

    tier, keys, set_cookie = identity_service.resolve_identity(request)
    view = identity_service.user_view(request, tier=tier)
    limit = metering_service.budget_for(tier)
    left = None if limit is None else metering_service.remaining(keys, tier)

    body = {
        "enabled": True,
        # 运行时真相：attach 失败（缺 authlib）时这里必须是 False，否则前端会
        # 渲染一个 404 的登录链接。
        "auth": identity_service.oauth_enabled,
        **view,
        "remainingSec": left,
        "limitSec": limit,
        "loginUrl": identity_service.OAUTH_LOGIN_PATH if identity_service.oauth_enabled else None,
        "logoutUrl": identity_service.OAUTH_LOGOUT_PATH if identity_service.oauth_enabled else None,
    }
    response = JSONResponse(body)
    if set_cookie:
        identity_service.set_anon_cookie(response, set_cookie)
    return response
