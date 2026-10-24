"""LB 会话申请与排队（移植自 `demo/server.py` 的 `/api/session` 与 `/api/queue*`）。

两条硬约束：未配 LB 时回 **404 而不是 403**（防探测，A.13 第 3 条）；`connect_url`
必然被下发（浏览器要直连），但 LB 的稳定地址永远不出服务端。
"""

from __future__ import annotations

import asyncio
from typing import Any
from urllib.parse import quote

import httpx
from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse
from loguru import logger

from app.config import demo
from app.services import identity_service, metering_service

LB_USER_AGENT = "speech-to-speech-console"
FAILURE_HEADER_NAMES = (
    "content-type",
    "server",
    "x-request-id",
    "ratelimit",
    "ratelimit-policy",
    "retry-after",
)


def base_url() -> str:
    return demo.lb_url.rstrip("/")


def enabled() -> bool:
    return bool(demo.lb_url)


def tracked_for(tier: str) -> bool:
    """要不要真记账：计量关着、或不限量档位，都不记。"""
    return demo.limiter_enabled and metering_service.budget_for(tier) is not None


async def _http(method: str, url: str, **kwargs: Any) -> httpx.Response:
    """单独一层：测试替换点。"""
    timeout = kwargs.pop("timeout", 15.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        return await client.request(method, url, **kwargs)


def headers(request: Request | None = None) -> dict[str, str]:
    """服务端发起会话申请时带的头。

    专用服务 token 让 Space 通过 HF ingress；登录访客的 OAuth token 另走
    `X-Reachy-Mini-Authorization`，因为 ingress 会把标准 `Authorization` 消耗掉。
    没配服务 token 时，登录用户的 token 兼两跳；匿名照常放行。
    """
    out = {"Content-Type": "application/json", "User-Agent": LB_USER_AGENT}
    user_token = identity_service.current_access_token(request) if request is not None else None
    gateway = demo.lb_hf_token.strip() or user_token
    if gateway:
        out["Authorization"] = f"Bearer {gateway}"
    if user_token:
        out["X-Reachy-Mini-Authorization"] = f"Bearer {user_token}"
    return out


def login_required(reason: str, set_cookie: str | None = None) -> JSONResponse:
    """浏览器登录流能认的 401。"""
    body = {
        "reason": reason,
        "loginUrl": identity_service.OAUTH_LOGIN_PATH if identity_service.oauth_enabled else None,
    }
    response = JSONResponse(body, status_code=401)
    if set_cookie:
        identity_service.set_anon_cookie(response, set_cookie)
    return response


def spent(tier: str, set_cookie: str | None = None) -> JSONResponse:
    """今天的额度已经花完（402，与 demo 一致）。"""
    response = JSONResponse({"tier": tier, "reason": "limit", "remainingSec": 0}, status_code=402)
    if set_cookie:
        identity_service.set_anon_cookie(response, set_cookie)
    return response


def log_failure(operation: str, response: httpx.Response) -> None:
    """记足够定位问题、但不含凭据的 ingress 元数据。"""
    seen = {name: value for name in FAILURE_HEADER_NAMES if (value := response.headers.get(name))}
    logger.warning(
        "load balancer {} failed status={} headers={} body={}",
        operation, response.status_code, seen, " ".join(response.text[:500].split()),
    )


def safe_json(response: httpx.Response) -> dict[str, Any]:
    try:
        body = response.json()
    except Exception:
        return {}
    return body if isinstance(body, dict) else {}


async def body_field(request: Request, field: str) -> str:
    """从 JSON 体里取一个字段，容忍 sendBeacon 的 blob 提交与空体。"""
    try:
        data = await request.json()
    except Exception:
        return ""
    return (data or {}).get(field, "") if isinstance(data, dict) else ""


async def finalize(
    data: dict[str, Any], keys: list[str], tier: str, tracked: bool, set_cookie: str | None
) -> JSONResponse:
    """快路径与排队认领共用的收尾：预留第一块、贴上计量字段、发匿名 cookie。"""
    left = None
    if demo.limiter_enabled and data.get("session_id"):
        # 每次授权都记一行，Web 搜索靠它判断会话是否活着；只有计量档位才真扣。
        await asyncio.to_thread(metering_service.begin, data["session_id"], keys, tier)
        if tracked:
            left = await asyncio.to_thread(metering_service.remaining, keys, tier)

    data.update({
        "tier": tier,
        "limited": tracked,
        "remainingSec": left,
        # 开着计量时每个档位都心跳（活体检测）；关掉就没人听。
        "heartbeatSec": metering_service.HEARTBEAT_SEC if demo.limiter_enabled else None,
    })
    response = JSONResponse(data)
    if set_cookie:
        identity_service.set_anon_cookie(response, set_cookie)
    return response


async def start(request: Request) -> JSONResponse:
    """申请一个会话：授权或排队票。"""
    reason = identity_service.oauth_login_required_reason(request)
    if reason:
        return login_required(reason)

    tier, keys, set_cookie = identity_service.resolve_identity(request)
    tracked = tracked_for(tier)

    # 预算已经没了就别去麻烦 LB：也不要把一个说不了话的人放进队列。
    if tracked:
        left = await asyncio.to_thread(metering_service.remaining, keys, tier)
        if left is not None and left <= 0:
            return spent(tier, set_cookie)

    try:
        lb = await _http("POST", f"{base_url()}/session", headers=headers(request), content="{}")
    except httpx.HTTPError as exc:
        logger.warning("load balancer unreachable: {}", exc)
        raise HTTPException(status_code=502, detail="Speech service unreachable.") from exc

    # 队列满：原样转 503 {state:"at_capacity"}，让客户端软提示「稍后再试」。
    if lb.status_code == 503 and safe_json(lb).get("state") == "at_capacity":
        response = JSONResponse({"state": "at_capacity"}, status_code=503)
        if set_cookie:
            identity_service.set_anon_cookie(response, set_cookie)
        return response

    if lb.status_code == 401:
        reason = safe_json(lb).get("reason", "login_required")
        logger.info("session authentication rejected: {}", reason)
        return login_required(reason, set_cookie)

    if lb.status_code != 200:
        log_failure("session handshake", lb)
        raise HTTPException(status_code=502, detail=f"Session handshake failed ({lb.status_code}).")

    data = lb.json()
    # 在排队：原样转回，且**不预留**——站着等不该花掉今天的额度。
    if data.get("state") == "queued":
        data["tier"] = tier
        response = JSONResponse(data)
        if set_cookie:
            identity_service.set_anon_cookie(response, set_cookie)
        return response
    return await finalize(data, keys, tier, tracked, set_cookie)


async def poll(request: Request, queue_id: str) -> JSONResponse:
    """轮询排队票：转位次；排到头部时此刻再校验预算并授权。"""
    reason = identity_service.oauth_login_required_reason(request)
    if reason:
        return login_required(reason)

    tier, keys, set_cookie = identity_service.resolve_identity(request)
    tracked = tracked_for(tier)

    try:
        lb = await _http("GET", f"{base_url()}/queue/{quote(queue_id, safe='')}", headers=headers(request))
    except httpx.HTTPError as exc:
        logger.warning("load balancer unreachable: {}", exc)
        raise HTTPException(status_code=502, detail="Speech service unreachable.") from exc

    if lb.status_code == 404:
        # 票号过期（停止轮询后被回收）：让客户端重开，而不是原地打转。
        response = JSONResponse({"state": "expired"}, status_code=404)
        if set_cookie:
            identity_service.set_anon_cookie(response, set_cookie)
        return response

    if lb.status_code != 200:
        log_failure("queue poll", lb)
        raise HTTPException(status_code=502, detail=f"Queue poll failed ({lb.status_code}).")

    data = lb.json()
    if data.get("state") == "queued":
        data["tier"] = tier
        response = JSONResponse(data)
        if set_cookie:
            identity_service.set_anon_cookie(response, set_cookie)
        return response

    # 拿到位置了：重新校验预算——等待期间额度可能已经在另一个标签页里花掉。
    # 此时 LB 上那个刚被认领的位子会由它自己的 pending 超时回收。
    if tracked:
        left = await asyncio.to_thread(metering_service.remaining, keys, tier)
        if left is not None and left <= 0:
            return spent(tier, set_cookie)
    return await finalize(data, keys, tier, tracked, set_cookie)


async def leave(queue_id: str, request: Request | None = None) -> None:
    """尽力而为：叫 LB 丢掉一张等待中的票。失败只记日志。"""
    url = f"{base_url()}/queue/{quote(queue_id, safe='')}"
    try:
        response = await _http("DELETE", url, headers=headers(request), timeout=5.0)
        if response.status_code not in {200, 404}:
            log_failure("queue leave", response)
    except httpx.HTTPError as exc:
        logger.warning("queue leave failed: {}", exc)
