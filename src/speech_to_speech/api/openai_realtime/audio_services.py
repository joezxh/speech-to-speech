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
from fastapi import FastAPI, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import JSONResponse

ASR_PATH = "/v1/audio/transcriptions"
TTS_PATH = "/v1/audio/speech"


def _route_exists(app: FastAPI, path: str) -> bool:
    return any(getattr(route, "path", None) == path for route in app.routes)


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

    @app.post(ASR_PATH)
    async def transcriptions(
        request: Request,
        file: UploadFile | None = None,
        language: str = Form("auto"),
        model: str = Form("qwen3-asr"),
    ):
        del model  # accepted for API compatibility; the pipeline handler owns the model
        stt, _ = find_handlers()
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
            text, detected = await asyncio.to_thread(stt._transcribe, audio, lang)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"asr failed: {exc}") from exc
        return JSONResponse({"text": text, "language": detected})

    @app.post(TTS_PATH)
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


__all__ = ["ASR_PATH", "TTS_PATH", "mount_audio_services"]
