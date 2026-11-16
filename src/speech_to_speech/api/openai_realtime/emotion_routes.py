"""Emotion proxy that reuses the existing emotion2vec_plus_large SER service.

The model weights (1.81 GB), funasr/modelscope dependencies and GPU inference
all stay in ``mediation_platform/mediation-deploy/ser``. This process only
forwards audio bytes over HTTP, so no new dependency or GPU memory is added to
the realtime pipeline. The browser's Authorization header is never forwarded.
"""
from __future__ import annotations

import os

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from loguru import logger

EMOTION_PATH = "/v1/audio/emotion"
HEALTH_PATH = "/v1/audio/emotion/health"


def _flag(name: str, default: str = "") -> bool:
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes", "on")


def _route_exists(app: FastAPI, path: str) -> bool:
    return any(getattr(route, "path", None) == path for route in app.routes)


def _upstream_response(upstream: httpx.Response) -> Response:
    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        media_type=upstream.headers.get("content-type"),
    )


def _proxy_error(status: int, code: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "retryable": status in (503, 504)}},
    )


def mount_emotion(app: FastAPI) -> None:
    """Register the emotion proxy only when enabled and fail-closed configured."""
    if not _flag("SER_ENABLED"):
        return
    base = os.environ.get("SER_BASE_URL", "").strip().rstrip("/")
    api_key = os.environ.get("SER_API_KEY", "").strip()
    if not base or not api_key:
        logger.warning("SER proxy disabled: SER_BASE_URL / SER_API_KEY not configured")
        return
    if _route_exists(app, EMOTION_PATH):
        return
    try:
        timeout = max(0.1, float(os.environ.get("SER_TIMEOUT_MS", "10000")) / 1000.0)
    except ValueError:
        timeout = 10.0

    @app.post(EMOTION_PATH)
    async def emotion(request: Request):
        body = await request.body()
        headers = {"X-API-Key": api_key}
        content_type = request.headers.get("content-type")
        if content_type:
            headers["Content-Type"] = content_type
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                upstream = await client.post(
                    f"{base}/v1/audio/emotion", content=body, headers=headers
                )
        except httpx.TimeoutException:
            logger.warning("SER proxy timeout after {}s", timeout)
            return _proxy_error(504, "SER_TIMEOUT")
        except httpx.RequestError:
            logger.warning("SER proxy unreachable: {}", base)
            return _proxy_error(503, "SER_UNREACHABLE")
        return _upstream_response(upstream)

    @app.get(HEALTH_PATH)
    async def emotion_health():
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                upstream = await client.get(
                    f"{base}/health", headers={"X-API-Key": api_key}
                )
        except httpx.TimeoutException:
            return _proxy_error(504, "SER_TIMEOUT")
        except httpx.RequestError:
            return _proxy_error(503, "SER_UNREACHABLE")
        return _upstream_response(upstream)


__all__ = ["EMOTION_PATH", "HEALTH_PATH", "mount_emotion"]
