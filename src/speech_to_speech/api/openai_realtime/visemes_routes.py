"""In-process audio-to-visemes REST endpoint, mirroring ASR/TTS.

Reuses the Wav2Vec2STVHandler already loaded in the pipeline pool (when
``enable_visemes`` is on).  No second model instance.  The default model is an
English phoneme CTC model — the capability endpoint reports its limits honestly.
"""
from __future__ import annotations

import asyncio
import io
import threading
from typing import Any, Iterable

import numpy as np
import soundfile as sf
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse

from speech_to_speech.api.openai_realtime.openapi_meta import error_response

VISEMES_PATH = "/v1/audio/visemes"
CAPABILITY_PATH = "/v1/audio/visemes/capability"

VISEMES_DESCRIPTION = """
**音频转口型（Speech-to-Visemes）**。把一段语音转成带时间戳的口型（viseme）序列，
用于驱动数字人 / 头像的嘴部动画。

* 请求体 `multipart/form-data`，音频放 `file` 字段；服务端重采样到 16 kHz 单声道，
  按 int16 PCM 送入音素识别模型。
* 输出 `visemes` 为数组，每项含 `viseme`（0–21，Microsoft 兼容口型编号）、
  `start_s` / `end_s`（相对音频起点的秒数）。
* 复用 pipeline 内已加载的 STV handler（需 `enable_visemes=true`），不额外加载模型；
  handler 未就绪时返回 503。
* 模型为英语音素模型，**中文效果未经验证**，请先用 capability 接口确认 `ready`。

```bash
curl -X POST http://localhost:8765/v1/audio/visemes \\
  -F "file=@speech.wav" \\
  -o visemes.json

# 查看能力（是否就绪、模型、采样率）
curl http://localhost:8765/v1/audio/visemes/capability
```
"""

CAPABILITY_DESCRIPTION = """
**口型能力查询**。返回口型服务的就绪状态、模型与口型编号范围。

* `ready=false` 表示 STV 未启用或音素模型不可达（此时 `/v1/audio/visemes` 返回 503）。
* `language` 标明当前模型是英语音素模型。

```bash
curl http://localhost:8765/v1/audio/visemes/capability
```
"""

_lock = threading.Lock()


def _route_exists(app: FastAPI, path: str) -> bool:
    return any(getattr(r, "path", None) == path for r in app.routes)


def find_stv_handler(pool: Iterable[Any]):
    """Find the STV handler in the pipeline pool (monkeypatchable in tests)."""
    for unit in pool:
        for handler in getattr(unit, "handlers", None) or []:
            if type(handler).__name__ == "Wav2Vec2STVHandler":
                return handler
    return None


def _decode_int16(data: bytes) -> np.ndarray:
    if not data:
        raise ValueError("empty audio")
    audio, sr = sf.read(io.BytesIO(data), dtype="float32", always_2d=False)
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    if sr != 16000:
        import librosa

        audio = librosa.resample(audio.astype(np.float32), orig_sr=sr, target_sr=16000)
    return np.clip(audio * 32767.0, -32768, 32767).astype(np.int16)


def mount_visemes(app: FastAPI, pool: Iterable[Any]) -> None:
    if _route_exists(app, VISEMES_PATH):
        return

    @app.post(
        VISEMES_PATH,
        summary="音频转口型（Visemes）",
        description=VISEMES_DESCRIPTION,
        tags=["音频能力"],
        response_description="口型序列",
        responses={
            200: {
                "description": "转换成功",
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "visemes": {
                                    "type": "array",
                                    "description": "按时间排序的口型序列。",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "viseme": {"type": "integer", "description": "口型编号 0–21。", "example": 6},
                                            "start_s": {"type": "number", "description": "起始秒（相对音频起点）。", "example": 0.02},
                                            "end_s": {"type": "number", "description": "结束秒。", "example": 0.08},
                                        },
                                    },
                                }
                            },
                        },
                        "example": {"visemes": [{"viseme": 21, "start_s": 0.02, "end_s": 0.08}, {"viseme": 6, "start_s": 0.08, "end_s": 0.15}]},
                    }
                },
            },
            400: error_response("音频缺失或无法解码。", "INVALID_AUDIO"),
            500: error_response("口型推理失败。", "VISEMES_FAILED"),
            503: error_response("STV handler 未就绪（模型不可达或未启用）。", "STV_UNAVAILABLE"),
        },
    )
    async def visemes(request: Request, file: UploadFile | None = File(
        None,
        description="待转换的语音音频；建议 16 kHz 单声道 WAV。",
    )):
        handler = find_stv_handler(pool)
        if handler is None:
            raise HTTPException(status_code=503, detail="STV handler unavailable")
        data = await file.read() if file is not None else await request.body()
        try:
            audio = _decode_int16(data)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"decode failed: {exc}") from exc
        try:
            # wav2vec2 pipeline is not thread-safe; serialize inference.
            with _lock:
                cues = await asyncio.to_thread(handler.speech_to_visemes, audio)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"visemes failed: {exc}") from exc
        return JSONResponse({"visemes": [c.model_dump() for c in cues]})

    @app.get(
        CAPABILITY_PATH,
        summary="口型能力查询",
        description=CAPABILITY_DESCRIPTION,
        tags=["音频能力"],
        response_description="口型服务能力",
        responses={
            200: {
                "description": "能力信息",
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "ready": {"type": "boolean", "description": "STV handler 是否已加载。", "example": True},
                                "model": {"type": "string", "example": "bookbot/wav2vec2-ljspeech-gruut"},
                                "sample_rate": {"type": "integer", "description": "模型要求的采样率。", "example": 16000},
                                "viseme_range": {
                                    "type": "array",
                                    "items": {"type": "integer"},
                                    "description": "口型编号范围。",
                                    "example": [0, 21],
                                },
                                "language": {"type": "string", "description": "音素模型语种。", "example": "en"},
                                "note": {"type": "string", "description": "效果说明与限制。"},
                            },
                        },
                        "example": {
                            "ready": True,
                            "model": "bookbot/wav2vec2-ljspeech-gruut",
                            "sample_rate": 16000,
                            "viseme_range": [0, 21],
                            "language": "en",
                            "note": "English phoneme visemes; Chinese quality not validated.",
                        },
                    }
                },
            }
        },
    )
    def capability():
        handler = find_stv_handler(pool)
        return {
            "ready": handler is not None,
            "model": "bookbot/wav2vec2-ljspeech-gruut",
            "sample_rate": 16000,
            "viseme_range": [0, 21],
            "language": "en",
            "note": "English phoneme visemes; Chinese quality not validated.",
        }


__all__ = ["VISEMES_PATH", "CAPABILITY_PATH", "find_stv_handler", "mount_visemes"]
