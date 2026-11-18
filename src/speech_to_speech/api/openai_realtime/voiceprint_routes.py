"""Voiceprint embedding endpoints, migrated from ``patch_voiceprint_embeddings.py``.

Mounted by ``create_app()`` so the routes exist both in the source tree and in
container images. Scheme C: the speaker encoder is a separate CPU-only slice of
the Base weights; TTS keeps its CustomVoice preset voices.
"""
from __future__ import annotations

import os
from typing import Any, Iterable

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse
from loguru import logger

from speech_to_speech.api.openai_realtime.openapi_meta import voiceprint_error_response

from speech_to_speech.voiceprint import service as voiceprint_service
from speech_to_speech.voiceprint.errors import VoiceprintErrorCode, error_body, http_status

EMBEDDINGS_PATH = "/v1/audio/embeddings"
CAPABILITY_PATH = "/v1/audio/embeddings/capability"

EMBEDDINGS_DESCRIPTION = """
**声纹嵌入（Voiceprint）**。把一段人声转成 L2 归一化的声纹向量，用于说话人注册与验证。

* **需要鉴权**：`Authorization: Bearer <token>`，token 由 `VOICEPRINT_API_KEY` 配置。
  * 请求头缺失或不是 `Bearer` 形式 → **401 `UNAUTHORIZED`**；
  * token 与配置不匹配 → **403 `FORBIDDEN`**。
* 请求体 `multipart/form-data`，音频放 `file` 字段；输入采样率不限，服务端重采样到 24 kHz（speaker encoder 采样率）。
* 输出维度见 `/v1/audio/embeddings/capability`（当前为 2048 维）。
* 音频只在内存中处理，不落盘、不进日志。
* `model` 传错（如 `model=rr`）返回 400 `MODEL_MISMATCH`；`purpose` 仅作审计标注，不参与校验。
* 错误体固定为 `{"error": {"code", "message", "stage", "retryable"}}`，`code` 为穷举枚举，调用方请按 `code` 分支、不要解析 `message`。

```bash
curl -X POST http://localhost:8765/v1/audio/embeddings \\
  -H "Authorization: Bearer $VOICEPRINT_API_KEY" \\
  -F "file=@voice.wav" \\
  -F "model=qwen3-tts-base-speaker" \\
  -F "purpose=registration"
```

```bash
# 查看能力（维度、是否就绪、设备）
curl -H "Authorization: Bearer $VOICEPRINT_API_KEY" \\
  http://localhost:8765/v1/audio/embeddings/capability
```
"""

CAPABILITY_DESCRIPTION = """
**声纹能力查询**。返回声纹服务的维度、就绪状态、设备与限制，便于调用方在注册前自检。

* 同样需要 `Authorization: Bearer <token>`：缺失 401，token 不匹配 403。
* `ready=false` 表示 encoder 尚未加载完成或未启用。
* 错误体与 `/v1/audio/embeddings` 一致：`{"error": {"code", "message", "stage", "retryable"}}`。

```bash
curl -H "Authorization: Bearer $VOICEPRINT_API_KEY" \\
  http://localhost:8765/v1/audio/embeddings/capability
```
"""


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

    @app.post(
        EMBEDDINGS_PATH,
        summary="声纹嵌入（Voiceprint）",
        description=EMBEDDINGS_DESCRIPTION,
        tags=["音频能力"],
        response_description="声纹向量",
        responses={
            200: {
                "description": "嵌入成功",
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "embedding": {
                                    "type": "array",
                                    "items": {"type": "number", "format": "float"},
                                    "description": "L2 归一化后的声纹向量，维度见 capability 接口。",
                                },
                                "dim": {"type": "integer", "description": "向量维度。", "example": 2048},
                                "model": {"type": "string", "description": "模型标识。", "example": "standalone-speaker-encoder@qwen3-speaker-encoder"},
                            },
                        },
                        "example": {"embedding": [0.0123, -0.0456], "dim": 2048, "model": "standalone-speaker-encoder@qwen3-speaker-encoder"},
                    }
                },
            },
            400: voiceprint_error_response("缺少音频文件（INVALID_REQUEST）或 model 与服务端配置不一致（MODEL_MISMATCH）。", "MODEL_MISMATCH"),
            401: voiceprint_error_response("缺少 Bearer 凭据，或请求头不是 `Bearer <token>` 形式。", "UNAUTHORIZED"),
            403: voiceprint_error_response("Bearer 凭据与 `VOICEPRINT_API_KEY` 不匹配。", "FORBIDDEN"),
            409: voiceprint_error_response("音频为静音（AUDIO_SILENT）、有效语音过短（AUDIO_TOO_SHORT）或未检测到语音（SPEECH_NOT_DETECTED）。", "AUDIO_SILENT"),
            413: voiceprint_error_response("音频超过体积上限。", "AUDIO_TOO_LARGE"),
            422: voiceprint_error_response("音频超过时长上限（AUDIO_TOO_LONG）或解码失败（AUDIO_UNDECODABLE）。", "AUDIO_UNDECODABLE"),
            500: voiceprint_error_response("推理失败或向量维度漂移。", "INFERENCE_FAILED"),
            503: voiceprint_error_response("服务端未配置凭据（AUTH_NOT_CONFIGURED）、模型不可用（MODEL_UNAVAILABLE）或队列已满（QUEUE_FULL）。", "QUEUE_FULL"),
            504: voiceprint_error_response("声纹推理超时（`VOICEPRINT_INFER_TIMEOUT_MS`，默认 3000 ms）。", "INFERENCE_TIMEOUT"),
        },
    )
    async def embeddings(
        request: Request,
        file: UploadFile | None = File(
            None,
            description="待提取声纹的音频文件；采样率不限，服务端重采样到 24 kHz。表单字段**可选**，留空时服务端回退读取原始请求体。",
        ),
        model: str = Form(
            "",
            description="模型名，须为 `qwen3-tts-base-speaker`（或留空使用默认）；传其它值返回 400 MODEL_MISMATCH。",
            examples=["qwen3-tts-base-speaker"],
        ),
        purpose: str = Form(
            "",
            description="用途标注（仅审计，不参与校验），如 `registration` / `verification`。",
            examples=["registration"],
        ),
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

    @app.get(
        CAPABILITY_PATH,
        summary="声纹能力查询",
        description=CAPABILITY_DESCRIPTION,
        tags=["音频能力"],
        response_description="声纹服务能力",
        responses={
            200: {
                "description": "能力信息",
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "model": {"type": "string", "example": "standalone-speaker-encoder@qwen3-speaker-encoder"},
                                "ready": {"type": "boolean", "description": "encoder 是否已就绪。", "example": True},
                                "device": {"type": "string", "description": "推理设备；`inherit` 表示跟随 pipeline 实际设备（当前为 CPU）。", "example": "inherit"},
                                "dim": {"type": "integer", "description": "输出向量维度。", "example": 2048},
                                "maxAudioMs": {"type": "integer", "description": "最长音频时长（毫秒）。", "example": 30000},
                                "maxBytes": {"type": "integer", "description": "最大请求体字节数。", "example": 10485760},
                            },
                        },
                        "example": {
                            "model": "standalone-speaker-encoder@qwen3-speaker-encoder",
                            "ready": True,
                            "device": "inherit",
                            "dim": 2048,
                            "maxAudioMs": 30000,
                            "maxBytes": 10485760,
                        },
                    }
                },
            },
            401: voiceprint_error_response("缺少 Bearer 凭据，或请求头不是 `Bearer <token>` 形式。", "UNAUTHORIZED"),
            403: voiceprint_error_response("Bearer 凭据与 `VOICEPRINT_API_KEY` 不匹配。", "FORBIDDEN"),
            503: voiceprint_error_response("服务端未配置凭据（AUTH_NOT_CONFIGURED），端点按 fail-closed 关闭。", "AUTH_NOT_CONFIGURED"),
        },
    )
    async def capability(request: Request):
        try:
            service.authorize(request.headers.get("authorization"))
        except voiceprint_service.VoiceprintRequestError as exc:
            return JSONResponse(status_code=exc.status_code, content=exc.body)
        return service.capability()


__all__ = ["CAPABILITY_PATH", "EMBEDDINGS_PATH", "mount_voiceprint"]
