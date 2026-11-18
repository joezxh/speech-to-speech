"""Standalone ASR / TTS REST endpoints backed by the in-process pipeline handlers.

Migrated from ``scripts/patch_pipeline_rest.py``. That script only injected these
routes into the container image at build time, so a source-tree start (PyCharm)
exposed the realtime WebSocket but no standalone audio endpoints.
"""
from __future__ import annotations

import asyncio
import io
from typing import Any, Iterable

import numpy as np
import soundfile as sf
from fastapi import FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import JSONResponse

from speech_to_speech.api.openai_realtime.openapi_meta import error_response

ASR_PATH = "/v1/audio/transcriptions"
TTS_PATH = "/v1/audio/speech"


ASR_DESCRIPTION = """
**语音转写（ASR）**。把一段音频转成文本，复用 pipeline 内已加载的 STT 模型
（当前配置为 SenseVoiceSmall，非自回归，RTF≈0.06；也兼容 Qwen3-ASR）。

* 请求体为 `multipart/form-data`，音频放 `file` 字段；支持 WAV/MP3/FLAC 等 soundfile 可解的格式。
* 服务端会重采样到 16 kHz 单声道后送入模型。
* 本接口**不占用**对话 slot：它直接调用 handler，不经过 VAD/会话状态机。

```bash
curl -X POST http://localhost:8765/v1/audio/transcriptions \\
  -F "file=@sample.wav" \\
  -F "language=zh" \\
  -F "model=qwen3-asr"
```

> `model` 字段仅为兼容 OpenAI 客户端而保留，服务端真正使用的是 pipeline 里配置好的模型，该值会被忽略。
"""

TTS_DESCRIPTION = """
**文本转语音（TTS）**。把文本合成为 WAV 音频，复用 pipeline 内已加载的 TTS 模型
（Qwen3-TTS，torch/cuda，流式 chunk=4）。

* 支持两种请求体：`application/json`（推荐）或 `multipart/form-data`。
* 走预设音色路径（CustomVoice）时 `voice` 取音色名（如 `Aiden`）；
  若 pipeline 配置了参考音频克隆，则忽略 `voice`，改用克隆音色。
* 返回 `audio/wav`（RIFF），采样率随实际输出（预设音色 24 kHz）。

```bash
curl -X POST http://localhost:8765/v1/audio/speech \\
  -H "Content-Type: application/json" \\
  -d '{"input":"你好，今天天气怎么样？","voice":"Aiden","language":"Auto"}' \\
  --output speech.wav
```

```bash
# multipart 形式
curl -X POST http://localhost:8765/v1/audio/speech \\
  -F "input=你好，今天天气怎么样？" \\
  -F "voice=Aiden" \\
  --output speech.wav
```
"""


def _route_exists(app: FastAPI, path: str) -> bool:
    return any(getattr(route, "path", None) == path for route in app.routes)


_STT_HANDLER_NAMES = ("Qwen3ASRSTTHandler", "SenseVoiceSTTHandler")


def find_stt_handler(pool: Iterable[Any]):
    """Return the first available STT handler (module-level, monkeypatchable)."""
    for unit in pool:
        for handler in getattr(unit, "handlers", None) or []:
            if type(handler).__name__ in _STT_HANDLER_NAMES:
                return handler
    return None


def mount_audio_services(app: FastAPI, pool: Iterable[Any]) -> None:
    """Register ASR/TTS routes once, reusing the handlers already living in the pool."""
    if _route_exists(app, ASR_PATH) and _route_exists(app, TTS_PATH):
        return

    def find_handlers():
        stt = None
        tts = None
        for unit in pool:
            for handler in getattr(unit, "handlers", None) or []:
                name = type(handler).__name__
                if stt is None and name == "Qwen3ASRSTTHandler":
                    stt = handler
                if tts is None and name == "Qwen3TTSHandler":
                    tts = handler
        return stt, tts

    def decode_audio(data: bytes) -> np.ndarray:
        audio, sample_rate = sf.read(io.BytesIO(data), dtype="float32", always_2d=False)
        if audio.ndim > 1:
            audio = audio.mean(axis=1)
        if sample_rate != 16000:
            import librosa

            audio = librosa.resample(audio.astype(np.float32), orig_sr=sample_rate, target_sr=16000)
        return np.asarray(audio, dtype=np.float32)

    @app.post(
        ASR_PATH,
        summary="语音转写（ASR）",
        description=ASR_DESCRIPTION,
        tags=["音频能力"],
        response_description="转写结果",
        responses={
            200: {
                "description": "转写成功",
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "text": {"type": "string", "description": "转写文本。", "example": "你好，请用一句话介绍你自己。"},
                                "language": {"type": "string", "description": "识别出的语言代码；未指定时回填模型默认语言。", "example": "zh"},
                            },
                        },
                        "example": {"text": "你好，请用一句话介绍你自己。", "language": "zh"},
                    }
                },
            },
            400: error_response("音频缺失或无法解码。", "INVALID_AUDIO"),
            500: error_response("模型推理失败。", "ASR_FAILED"),
            503: error_response("pipeline 内没有可用的 STT handler。", "STT_UNAVAILABLE"),
        },
    )
    async def transcriptions(
        request: Request,
        file: UploadFile | None = File(
            None,
            description="待转写音频文件；建议 16 kHz 单声道 WAV。",
        ),
        language: str = Form(
            "auto",
            description="语种：`auto` 表示自动检测；也可显式指定如 `zh`、`en`。",
            examples=["auto", "zh"],
        ),
        model: str = Form(
            "qwen3-asr",
            description="兼容字段，仅为 OpenAI 客户端保留；服务端忽略该值，使用 pipeline 配置的模型。",
            examples=["qwen3-asr"],
        ),
    ):
        del model  # accepted for API compatibility; the pipeline handler owns the model
        stt = find_stt_handler(pool)
        if stt is None:
            raise HTTPException(status_code=503, detail="STT handler unavailable")
        data = await file.read() if file is not None else await request.body()
        if not data:
            raise HTTPException(status_code=400, detail="no audio provided")
        try:
            audio = decode_audio(data)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"decode failed: {exc}") from exc
        lang = None if (language or "auto").strip().lower() in ("", "auto") else language
        try:
            if hasattr(stt, "_transcribe"):
                text, detected = await asyncio.to_thread(stt._transcribe, audio, lang)
            else:  # SenseVoiceSTTHandler
                text = await asyncio.to_thread(stt._generate, audio)
                detected = lang or "zh"
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"asr failed: {exc}") from exc
        return JSONResponse({"text": text, "language": detected})

    @app.post(
        TTS_PATH,
        summary="文本转语音（TTS）",
        description=TTS_DESCRIPTION,
        tags=["音频能力"],
        response_description="WAV 音频",
        responses={
            200: {
                "description": "合成成功，返回 audio/wav（RIFF）。",
                "content": {"audio/wav": {"schema": {"type": "string", "format": "binary"}}},
            },
            400: error_response("输入文本为空。", "EMPTY_INPUT"),
            500: error_response("合成失败。", "TTS_FAILED"),
            503: error_response("pipeline 内没有可用的 TTS handler。", "TTS_UNAVAILABLE"),
        },
        openapi_extra={
            "requestBody": {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "input": {
                                    "type": "string",
                                    "description": "要合成的文本。",
                                    "example": "你好，今天天气怎么样？",
                                },
                                "voice": {
                                    "type": "string",
                                    "description": "预设音色名（CustomVoice）；配置了参考音频克隆时忽略该值。",
                                    "example": "Aiden",
                                },
                                "language": {
                                    "type": "string",
                                    "description": "合成语言，`Auto` 表示自动。",
                                    "example": "Auto",
                                },
                            },
                            "required": ["input"],
                        },
                        "example": {"input": "你好，今天天气怎么样？", "voice": "Aiden", "language": "Auto"},
                    },
                    "multipart/form-data": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "input": {"type": "string", "example": "你好，今天天气怎么样？"},
                                "voice": {"type": "string", "example": "Aiden"},
                                "language": {"type": "string", "example": "Auto"},
                            },
                            "required": ["input"],
                        }
                    },
                },
            }
        },
    )
    async def speech(request: Request):
        _, tts = find_handlers()
        if tts is None:
            raise HTTPException(status_code=503, detail="TTS handler unavailable")
        if "application/json" in request.headers.get("content-type", ""):
            payload = await request.json()
            text = str(payload.get("input") or payload.get("text") or "")
            voice = str(payload.get("voice") or payload.get("speaker") or "Aiden")
            language = str(payload.get("language") or "Auto")
        else:
            payload = await request.form()
            text = str(payload.get("input") or payload.get("text") or "")
            voice = str(payload.get("voice") or payload.get("speaker") or "Aiden")
            language = str(payload.get("language") or "Auto")
        if not text.strip():
            raise HTTPException(status_code=400, detail="empty input")
        try:
            # Clone path must consume the synchronous generator inside a worker
            # thread; iterating it in the async endpoint blocks the event loop.
            is_clone = bool(
                hasattr(tts, "_has_voice_clone_reference") and tts._has_voice_clone_reference()
            )
            chunks: list[np.ndarray] = []
            sample_rate = 24000
            if is_clone:

                def collect_clone():
                    collected: list[np.ndarray] = []
                    rate = 24000
                    for item in tts.model.generate_voice_clone_streaming(
                        text=text,
                        language=language,
                        ref_audio=getattr(tts, "ref_audio", None),
                        ref_spk=getattr(tts, "ref_spk", None),
                        ref_rvq=getattr(tts, "ref_rvq", None),
                        ref_text=getattr(tts, "ref_text", "") or "",
                        chunk_size=getattr(tts, "streaming_chunk_size", 4),
                        non_streaming_mode=False,
                    ):
                        array, chunk_rate = tts._prepare_audio_chunk(item)
                        if array is None or chunk_rate is None:
                            continue
                        flat = np.asarray(array).flatten()
                        if flat.size == 0:
                            continue
                        collected.append(flat)
                        rate = chunk_rate
                    return collected, rate

                chunks, sample_rate = await asyncio.to_thread(collect_clone)
            else:
                audio_arrays, sample_rate = await asyncio.to_thread(
                    tts.model.generate_custom_voice,
                    text=text,
                    speaker=voice,
                    language=language,
                    non_streaming_mode=True,
                )
                for chunk in audio_arrays:
                    array = chunk[0] if isinstance(chunk, tuple) else chunk
                    chunks.append(np.asarray(array).flatten())
            waveform = np.concatenate(chunks) if chunks else np.zeros(0, dtype=np.float32)
            if waveform.size == 0:
                raise ValueError("tts produced empty audio")
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"tts failed: {exc}") from exc
        buffer = io.BytesIO()
        sf.write(buffer, waveform, sample_rate, format="WAV")
        return Response(content=buffer.getvalue(), media_type="audio/wav")


__all__ = ["ASR_PATH", "TTS_PATH", "find_stt_handler", "mount_audio_services"]
