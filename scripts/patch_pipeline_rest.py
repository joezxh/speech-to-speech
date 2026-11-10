import io
import sys

TARGET = "/usr/src/app/src/speech_to_speech/api/openai_realtime/websocket_router.py"
MARKER = "    app = FastAPI(lifespan=lifespan)\n"

NEW_BLOCK = '''    # ── Standalone ASR / TTS REST endpoints (reuse in-process models) ──
    import asyncio as _asyncio
    import io as _io
    import numpy as _np
    import soundfile as _sf
    from fastapi import Request, UploadFile, Form, HTTPException, Response
    from fastapi.responses import JSONResponse

    def _find_handlers():
        stt = None
        tts = None
        for unit in pool:
            for h in (getattr(unit, "handlers", None) or []):
                tn = type(h).__name__
                if stt is None and tn == "Qwen3ASRSTTHandler":
                    stt = h
                if tts is None and tn == "Qwen3TTSHandler":
                    tts = h
        return stt, tts

    def _decode_audio_asr(data: bytes):
        audio, sr = _sf.read(_io.BytesIO(data), dtype="float32", always_2d=False)
        if audio.ndim > 1:
            audio = audio.mean(axis=1)
        if sr != 16000:
            import librosa

            audio = librosa.resample(audio.astype(_np.float32), orig_sr=sr, target_sr=16000)
        return _np.asarray(audio, dtype=_np.float32)

    @app.post("/v1/audio/transcriptions")
    async def rest_transcriptions(
        request: Request,
        file: UploadFile | None = None,
        language: str = Form("auto"),
        model: str = Form("qwen3-asr"),
    ):
        stt, _ = _find_handlers()
        if stt is None:
            raise HTTPException(status_code=503, detail="STT handler unavailable")
        data = None
        if file is not None:
            data = await file.read()
        else:
            body = await request.body()
            if body:
                data = body
        if not data:
            raise HTTPException(status_code=400, detail="no audio provided")
        try:
            audio = _decode_audio_asr(data)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"decode failed: {exc}")
        lang = None if (language or "auto").strip().lower() in ("", "auto") else language
        try:
            text, detected = await _asyncio.to_thread(stt._transcribe, audio, lang)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"asr failed: {exc}")
        return JSONResponse({"text": text, "language": detected})

    @app.post("/v1/audio/speech")
    async def rest_speech(request: Request):
        _, tts = _find_handlers()
        if tts is None:
            raise HTTPException(status_code=503, detail="TTS handler unavailable")
        ctype = request.headers.get("content-type", "")
        if "application/json" in ctype:
            data = await request.json()
            text = str(data.get("input") or data.get("text") or "")
            voice = str(data.get("voice") or data.get("speaker") or "Aiden")
            language = str(data.get("language") or "Auto")
            response_format = str(data.get("response_format") or "wav").lower()
        else:
            form = await request.form()
            text = str(form.get("input") or form.get("text") or "")
            voice = str(form.get("voice") or form.get("speaker") or "Aiden")
            language = str(form.get("language") or "Auto")
            response_format = str(form.get("response_format") or "wav").lower()
        if not text.strip():
            raise HTTPException(status_code=400, detail="empty input")
        try:
            audio_arrays, sr = await _asyncio.to_thread(
                tts.model.generate_custom_voice,
                text=text,
                speaker=voice,
                language=language,
                non_streaming_mode=True,
            )
            chunks = []
            for c in audio_arrays:
                arr = c[0] if isinstance(c, tuple) else c
                chunks.append(_np.asarray(arr).flatten())
            waveform = _np.concatenate(chunks) if chunks else _np.zeros(0, dtype=_np.float32)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"tts failed: {exc}")
        buf = _io.BytesIO()
        _sf.write(buf, waveform, sr, format="WAV")
        return Response(content=buf.getvalue(), media_type="audio/wav")
'''

def main() -> None:
    with open(TARGET) as f:
        content = f.read()
    if "rest_transcriptions" in content:
        print("PATCH ALREADY APPLIED")
        return
    if MARKER not in content:
        print("MARKER NOT FOUND")
        sys.exit(1)
    content = content.replace(MARKER, MARKER + NEW_BLOCK, 1)
    with open(TARGET, "w") as f:
        f.write(content)
    print("PATCH APPLIED")

if __name__ == "__main__":
    main()
