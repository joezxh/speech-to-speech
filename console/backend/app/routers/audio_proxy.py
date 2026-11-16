"""`/v1/audio/*`：ASR / TTS / 声纹 / 情感的反代面（spec §5.4）。

路径与 pipeline 侧完全一致，调用方（Java 网关、语音页）不需要改地址。
`CONSOLE_LB_MODE=off` 时这些路由仍然注册，但一律回 501 `lb_disabled`——
不注册的话 GET 会命中 SPA catch-all 拿到 200 index.html（探针解析 JSON 会炸），
POST 会拿到 405。
"""

from __future__ import annotations

from fastapi import APIRouter, Request

from app.services import audio_proxy_service

router = APIRouter(tags=["audio-proxy"])


@router.post("/v1/audio/transcriptions")
async def transcriptions(request: Request):
    return await audio_proxy_service.forward("asr", request)


@router.post("/v1/audio/speech")
async def speech(request: Request):
    return await audio_proxy_service.forward("tts", request)


@router.post("/v1/audio/embeddings")
async def embeddings(request: Request):
    return await audio_proxy_service.forward("voiceprint", request)


@router.get("/v1/audio/embeddings/capability")
async def embeddings_capability(request: Request):
    return await audio_proxy_service.forward("voiceprint_capability", request)


@router.post("/v1/audio/emotion")
async def emotion(request: Request):
    return await audio_proxy_service.forward("emotion", request)


@router.get("/v1/audio/emotion/health")
async def emotion_health(request: Request):
    return await audio_proxy_service.forward("emotion_health", request)
