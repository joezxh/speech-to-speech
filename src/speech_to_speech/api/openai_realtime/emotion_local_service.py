"""In-process SenseVoice SER endpoints (local provider), mirroring ASR/TTS.

Registered instead of (not alongside) the emotion2vec proxy when
``SER_PROVIDER=local``.  Reuses the ``SenseVoiceSTTHandler`` already loaded in
the pipeline pool — no second model instance, no extra port.
"""
from __future__ import annotations

import asyncio
import io
import os
import threading
import time
from typing import Any, Iterable

import numpy as np
import soundfile as sf
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse

from speech_to_speech.api.openai_realtime.openapi_meta import error_response, json_response

from speech_to_speech.STT.sense_voice_emotion import (
    SERRejection,
    emotion_token_ids,
    map_emotion,
    ser_error_body,
    slice_emotion_logits,
    probs_from_logits,
    threshold_gate,
)

RECOGNIZE_PATH = "/recognize"
EMOTION_PATH = "/v1/audio/emotion"
HEALTH_PATH = "/v1/audio/emotion/health"

_LABELS = ["calm", "happy", "anxious", "agitated", "anger", "threat"]
_MIN_CONF = float(os.environ.get("SER_MIN_CONFIDENCE", "0.55"))
_MIN_MARGIN = float(os.environ.get("SER_MIN_MARGIN", "0.15"))
_SILENCE_RMS = float(os.environ.get("SER_SILENCE_RMS_FLOOR", "0.0001"))
_MAX_INFLIGHT = int(os.environ.get("SER_MAX_INFLIGHT", "2"))
_WAIT_TIMEOUT_S = float(os.environ.get("SER_WAIT_TIMEOUT_S", "0.5"))

RECOGNIZE_DESCRIPTION = """
**语音情感识别（SER，内嵌 SenseVoice）**。识别一段语音的情绪，返回平台情感标签、置信度与判别余量。

* 请求体 `multipart/form-data`，音频放 `file` 字段；重采样到 16 kHz 单声道。
* **两个等价路径**：`POST /recognize` 与 `POST /v1/audio/emotion` 行为完全一致。
* 复用 pipeline 内已加载的 SenseVoice 模型（`SER_PROVIDER=local`），不额外占显存、不额外起端口。
* 输出 `emotion` 取值 `calm / happy / anxious / agitated / anger / threat`（6 类）；
  `confidence` 为 top1 概率，`margin` 为 top1−top2 差值，`events.laughter` 标记是否检出笑声（AED 事件）。
* **拒答而非静默降级**：全静音、置信度低于 `SER_MIN_CONFIDENCE`、判别余量低于 `SER_MIN_MARGIN`
  或模型给出 `EMO_UNKNOWN` 时，返回 409 且带结构化 `error.code`，绝不回退成 `calm`。

```bash
curl -X POST http://localhost:8765/recognize \\
  -F "file=@speech.wav" \\
  -F "sample_rate=16000" \\
  -F "language=zh"
```

```bash
# 等价别名
curl -X POST http://localhost:8765/v1/audio/emotion \\
  -F "file=@speech.wav" -F "sample_rate=16000" -F "language=zh"
```
"""

HEALTH_DESCRIPTION = """
**情感服务健康检查**。返回当前 provider、模型、就绪状态与支持的标签集。

* `ready=false` 表示 pipeline 内没有 SenseVoice handler（例如 STT 仍用别的后端）。
* `provider` 恒为 `local`（proxy 模式下由 emotion2vec 的同名路径提供，语义相同）。

```bash
curl http://localhost:8765/v1/audio/emotion/health
```
"""


def _route_exists(app: FastAPI, path: str) -> bool:
    return any(getattr(r, "path", None) == path for r in app.routes)


def find_ser_handler(pool: Iterable[Any]):
    """Find the SenseVoice handler in the pipeline pool (monkeypatchable in tests)."""
    for unit in pool:
        for handler in getattr(unit, "handlers", None) or []:
            if type(handler).__name__ == "SenseVoiceSTTHandler":
                return handler
    return None


def _decode(data: bytes) -> np.ndarray:
    if not data:
        raise SERRejection("INVALID_AUDIO", "empty audio")
    try:
        audio, sr = sf.read(io.BytesIO(data), dtype="float32", always_2d=False)
    except Exception as exc:
        raise SERRejection("INVALID_AUDIO", f"decode failed: {exc}") from exc
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    if sr != 16000:
        import librosa

        audio = librosa.resample(audio.astype(np.float32), orig_sr=sr, target_sr=16000)
    return np.asarray(audio, dtype=np.float32)


def mount_emotion_local(app: FastAPI, pool: Iterable[Any]) -> None:
    """Register local SenseVoice SER routes when SER_PROVIDER=local."""
    provider = os.environ.get("SER_PROVIDER", "proxy").strip().lower()
    if provider != "local":
        return
    if _route_exists(app, RECOGNIZE_PATH):
        return

    sem = threading.Semaphore(_MAX_INFLIGHT)
    ids_cache: dict[str, int] | None = None

    def _infer(handler, audio: np.ndarray) -> dict:
        nonlocal ids_cache
        rms = float(np.sqrt(np.mean(np.square(audio, dtype=np.float64))))
        if rms < _SILENCE_RMS:
            raise SERRejection("SILENCE", "silent audio")
        raw = handler.recognize(audio)
        raw_label = str(raw.get("raw", "")).upper()
        laughter = bool(raw.get("laughter", False))
        conf = float(raw.get("confidence", 0.0))
        margin = float(raw.get("margin", 0.0))
        if ids_cache is None:
            ids_cache = emotion_token_ids()
        threshold_gate(conf, margin, _MIN_CONF, _MIN_MARGIN)
        emotion = map_emotion(raw_label, laughter=laughter)
        return {
            "emotion": emotion,
            "confidence": round(conf, 4),
            "margin": round(margin, 4),
            "rawLabel": raw_label,
            "events": {"laughter": laughter},
            "model": "SenseVoiceSmall",
            "labels_supported": _LABELS,
        }

    async def _recognize(
        request: Request,
        file: UploadFile | None = File(
            None,
            description="待分析的情感语音；建议 16 kHz 单声道 WAV。",
        ),
        sample_rate: int = Form(
            16000,
            description="音频采样率（Hz）；与服务端实际读取结果不一致时以文件头为准。",
            examples=[16000],
        ),
        language: str = Form(
            "zh",
            description="语种提示，影响模型的语言判定。",
            examples=["zh", "en"],
        ),
    ):
        handler = find_ser_handler(pool)
        if handler is None:
            raise HTTPException(status_code=503, detail="SER handler unavailable")
        data = await file.read() if file is not None else await request.body()
        if not sem.acquire(blocking=False):
            # short-deadline wait instead of instant 429
            got = await asyncio.to_thread(sem.acquire, True, _WAIT_TIMEOUT_S)
            if not got:
                return JSONResponse(
                    ser_error_body("BUSY", "concurrency full"), status_code=429
                )
        try:
            audio = _decode(data)
            result = await asyncio.to_thread(_infer, handler, audio)
            return JSONResponse(result)
        except SERRejection as exc:
            return JSONResponse(ser_error_body(exc.reason, exc.detail), status_code=409)
        except HTTPException:
            raise
        except Exception as exc:
            return JSONResponse(ser_error_body("INFER_FAILED", str(exc)), status_code=500)
        finally:
            sem.release()

    _recognize_responses = {
        200: json_response(
            "识别成功",
            {
                "type": "object",
                "properties": {
                    "emotion": {
                        "type": "string",
                        "description": "平台情感标签（6 类）。",
                        "example": "happy",
                    },
                    "confidence": {
                        "type": "number",
                        "description": "top1 概率（0–1）。",
                        "example": 0.9123,
                    },
                    "margin": {
                        "type": "number",
                        "description": "top1 与 top2 的概率差（0–1），越大越可分。",
                        "example": 0.7841,
                    },
                    "rawLabel": {
                        "type": "string",
                        "description": "模型原始情感标签。",
                        "example": "HAPPY",
                    },
                    "events": {
                        "type": "object",
                        "description": "音频事件（AED）检测结果。",
                        "properties": {
                            "laughter": {
                                "type": "boolean",
                                "description": "是否检出笑声事件。",
                                "example": True,
                            }
                        },
                    },
                    "model": {"type": "string", "example": "SenseVoiceSmall"},
                    "labels_supported": {
                        "type": "array",
                        "items": {"type": "string"},
                        "example": _LABELS,
                    },
                },
            },
            example={
                "emotion": "happy",
                "confidence": 0.9123,
                "margin": 0.7841,
                "rawLabel": "HAPPY",
                "events": {"laughter": True},
                "model": "SenseVoiceSmall",
                "labels_supported": _LABELS,
            },
        ),
        409: error_response("拒答：全静音 / 置信度不足 / 判别余量不足 / 标签无法映射。", "SILENCE"),
        429: error_response("并发已满且短截止等待超时。", "BUSY"),
        500: error_response("推理失败。", "INFER_FAILED"),
        503: error_response("pipeline 内没有 SenseVoice handler。", "SER_UNAVAILABLE"),
    }

    app.add_api_route(
        RECOGNIZE_PATH,
        _recognize,
        methods=["POST"],
        summary="语音情感识别（SER）",
        description=RECOGNIZE_DESCRIPTION,
        tags=["音频能力"],
        response_description="情感识别结果",
        responses=_recognize_responses,
    )
    app.add_api_route(
        EMOTION_PATH,
        _recognize,
        methods=["POST"],
        summary="语音情感识别（SER，兼容别名）",
        description=RECOGNIZE_DESCRIPTION,
        tags=["音频能力"],
        response_description="情感识别结果",
        responses=_recognize_responses,
    )

    @app.get(
        HEALTH_PATH,
        summary="情感服务健康检查",
        description=HEALTH_DESCRIPTION,
        tags=["音频能力"],
        response_description="情感服务状态",
        responses={
            200: json_response(
                "健康信息",
                {
                    "type": "object",
                    "properties": {
                        "status": {"type": "string", "example": "ok"},
                        "provider": {"type": "string", "example": "local"},
                        "model": {"type": "string", "example": "SenseVoiceSmall"},
                        "ready": {"type": "boolean", "description": "handler 是否就绪。", "example": True},
                        "labels_supported": {
                            "type": "array",
                            "items": {"type": "string"},
                            "example": _LABELS,
                        },
                        "max_inflight": {"type": "integer", "example": _MAX_INFLIGHT},
                        "persistence": {
                            "type": "boolean",
                            "description": "服务端是否持久化音频（恒为 false）。",
                            "example": False,
                        },
                    },
                },
                example={
                    "status": "ok",
                    "provider": "local",
                    "model": "SenseVoiceSmall",
                    "ready": True,
                    "labels_supported": _LABELS,
                    "max_inflight": _MAX_INFLIGHT,
                    "persistence": False,
                },
            )
        },
    )
    def health():
        return {
            "status": "ok",
            "provider": "local",
            "model": "SenseVoiceSmall",
            "ready": find_ser_handler(pool) is not None,
            "labels_supported": _LABELS,
            "max_inflight": _MAX_INFLIGHT,
            "persistence": False,
        }


__all__ = [
    "RECOGNIZE_PATH",
    "EMOTION_PATH",
    "HEALTH_PATH",
    "find_ser_handler",
    "mount_emotion_local",
]
