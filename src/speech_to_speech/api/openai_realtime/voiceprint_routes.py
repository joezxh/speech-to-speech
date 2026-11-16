"""Voiceprint embedding endpoints, migrated from ``patch_voiceprint_embeddings.py``.

Mounted by ``create_app()`` so the routes exist both in the source tree and in
container images. Scheme C: the speaker encoder is a separate CPU-only slice of
the Base weights; TTS keeps its CustomVoice preset voices.
"""
from __future__ import annotations

import os
from typing import Any, Iterable

from fastapi import FastAPI, Form, Request, UploadFile
from fastapi.responses import JSONResponse
from loguru import logger

from speech_to_speech.voiceprint import service as voiceprint_service
from speech_to_speech.voiceprint.errors import VoiceprintErrorCode, error_body, http_status

EMBEDDINGS_PATH = "/v1/audio/embeddings"
CAPABILITY_PATH = "/v1/audio/embeddings/capability"


def _flag(name: str, default: str = "") -> bool:
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes", "on")


def _route_exists(app: FastAPI, path: str) -> bool:
    return any(getattr(route, "path", None) == path for route in app.routes)


def mount_voiceprint(app: FastAPI, pool: Iterable[Any]) -> None:
    """Register voiceprint routes only when enabled and configured."""
    if not _flag("VOICEPRINT_ENABLED", "false"):
        return
    if _route_exists(app, EMBEDDINGS_PATH):
        return

    service = voiceprint_service.VoiceprintService(
        api_key=os.environ.get("VOICEPRINT_API_KEY"),
        model_name=os.environ.get("VOICEPRINT_MODEL") or None,
        max_audio_ms=int(os.environ.get("VOICEPRINT_MAX_AUDIO_MS", "30000")),
        max_bytes=int(os.environ.get("VOICEPRINT_MAX_BYTES", "10485760")),
        min_speech_ms=int(os.environ.get("VOICEPRINT_MIN_SPEECH_MS", "800")),
        strict_reject=_flag("VOICEPRINT_STRICT_REJECT", "false"),
        queue_capacity=int(os.environ.get("VOICEPRINT_QUEUE_CAPACITY", "16")),
        max_concurrency=int(os.environ.get("VOICEPRINT_MAX_CONCURRENCY", "4")),
        infer_timeout_ms=int(os.environ.get("VOICEPRINT_INFER_TIMEOUT_MS", "3000")),
        device=os.environ.get("VOICEPRINT_DEVICE") or None,
    )
    service.attach_pool(pool, os.environ.get("VOICEPRINT_ENCODER_DIR") or None)

    @app.post(EMBEDDINGS_PATH)
    async def embeddings(
        request: Request,
        file: UploadFile | None = None,
        model: str = Form(""),
        purpose: str = Form(""),
    ):
        try:
            service.authorize(request.headers.get("authorization"))
        except voiceprint_service.VoiceprintRequestError as exc:
            return JSONResponse(status_code=exc.status_code, content=exc.body)
        data = await file.read() if file is not None else b""
        try:
            result = service.embed(data, model=model or None, purpose=purpose or None)
        except voiceprint_service.VoiceprintRequestError as exc:
            return JSONResponse(status_code=exc.status_code, content=exc.body)
        except Exception as exc:
            # Never leak a stack trace, path or credential fragment to the caller.
            logger.warning("voiceprint inference failed: {}", type(exc).__name__)
            code = VoiceprintErrorCode.INTERNAL_ERROR
            return JSONResponse(status_code=http_status(code), content=error_body(code))
        return result

    @app.get(CAPABILITY_PATH)
    async def capability(request: Request):
        try:
            service.authorize(request.headers.get("authorization"))
        except voiceprint_service.VoiceprintRequestError as exc:
            return JSONResponse(status_code=exc.status_code, content=exc.body)
        return service.capability()


__all__ = ["CAPABILITY_PATH", "EMBEDDINGS_PATH", "mount_voiceprint"]
