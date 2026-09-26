import asyncio
import base64
import os
import sys
import time

import numpy as np


def load_wav(path):
    import soundfile as sf

    data, sr = sf.read(path, dtype="int16", always_2d=False)
    if data.ndim > 1:
        data = data[:, 0]
    if sr != 16000:
        import torch
        import torchaudio

        x = torch.from_numpy(data.astype(np.float32)) / 32768.0
        x = torchaudio.functional.resample(x, sr, 16000)
        data = (x.numpy() * 32768.0).astype(np.int16)
        sr = 16000
    return data, sr


async def main():
    args = sys.argv[1:]
    path = args[0] if args else None
    phrases = int(os.environ.get("PHRASES", "1"))
    gap = float(os.environ.get("GAP", "2.0"))

    if not path or not os.path.exists(path):
        for c in [
            "/usr/src/app/src/speech_to_speech/TTS/ref_audio.wav",
            "/app/src/speech_to_speech/TTS/ref_audio.wav",
            "/opt/speech-to-speech/src/speech_to_speech/TTS/ref_audio.wav",
        ]:
            if os.path.exists(c):
                path = c
                break
    if not path:
        print("ref_audio.wav not found")
        return

    data, sr = load_wav(path)
    print(f"LOADED {path} sr={sr} samples={len(data)} dur={len(data)/sr:.2f}s")

    from openai import AsyncOpenAI

    client = AsyncOpenAI(
        base_url="http://127.0.0.1:8765/v1",
        websocket_base_url="ws://127.0.0.1:8765/v1",
        api_key="local",
    )

    t0 = time.monotonic()
    timeline = []
    first_audio_t = [None]
    stop = asyncio.Event()

    async def receiver(conn):
        while not stop.is_set():
            try:
                ev = await asyncio.wait_for(conn.recv(), timeout=60)
            except asyncio.TimeoutError:
                break
            et = getattr(ev, "type", None)
            t = time.monotonic()
            if et == "input_audio_buffer.speech_started":
                timeline.append((t, "speech_started"))
            elif et == "input_audio_buffer.speech_stopped":
                timeline.append((t, "speech_stopped(srv)"))
            elif et == "conversation.item.input_audio_transcription.completed":
                timeline.append((t, "TRANSCRIPT", getattr(ev, "transcript", "")))
            elif et == "response.created":
                timeline.append((t, "response.created"))
            elif et == "response.output_audio.delta":
                if first_audio_t[0] is None:
                    first_audio_t[0] = t
                    timeline.append((t, "FIRST_AUDIO_DELTA"))
            elif et == "response.output_audio.done":
                timeline.append((t, "output_audio.done"))
            elif et == "response.done":
                st = getattr(getattr(ev, "response", None), "status", None)
                timeline.append((t, "response.done", st))
            elif et == "error":
                e = getattr(ev, "error", None)
                print("SERVER ERROR:", getattr(e, "message", None))
            else:
                print(f"[other event] {et}")

    async def send_audio(conn, pcm, label):
        chunk = 1024
        n = len(pcm)
        i = 0
        while i < n:
            seg = pcm[i : i + chunk]
            await conn.send(
                {
                    "type": "input_audio_buffer.append",
                    "audio": base64.b64encode(seg.tobytes()).decode(),
                }
            )
            i += chunk
            await asyncio.sleep(chunk / sr)

    async with client.realtime.connect(model="local") as conn:
        await conn.send(
            {
                "type": "session.update",
                "session": {
                    "type": "realtime",
                    "audio": {
                        "input": {
                            "turn_detection": {
                                "type": "server_vad",
                                "interrupt_response": True,
                            }
                        }
                    },
                },
            }
        )
        recv_task = asyncio.create_task(receiver(conn))

        for p in range(phrases):
            if p > 0:
                print(f"--- gap {gap}s before phrase {p+1} ---")
                await asyncio.sleep(gap)
            await send_audio(conn, data, "phrase")
        # trailing silence so server VAD detects end-of-speech
        await send_audio(conn, np.zeros(sr * 2, dtype=np.int16), "silence")

        t_send_done = time.monotonic()
        timeline.append((t_send_done, "audio_send_done"))

        deadline = t0 + 70
        while not stop.is_set() and time.monotonic() < deadline:
            await asyncio.sleep(0.1)
        await asyncio.sleep(2.0)
        stop.set()

    print("\n=== TIMELINE (relative to t0) ===")
    for row in timeline:
        rel = row[0] - t0
        if len(row) == 3 and row[1] == "TRANSCRIPT":
            print(f"  +{rel:6.2f}s  TRANSCRIPT: {row[2]!r}")
        elif len(row) == 3:
            print(f"  +{rel:6.2f}s  {row[1]}: {row[2]}")
        else:
            print(f"  +{rel:6.2f}s  {row[1]}")

    fa = first_audio_t[0]
    if fa is not None:
        sst = [r[0] for r in timeline if r[1] == "speech_stopped(srv)"]
        base = sst[-1] if sst else t_send_done
        print(f"\nTTFA (t0 -> first audio):      {fa - t0:.2f}s")
        print(f"Latency after speech end:      {fa - base:.2f}s")
    else:
        print("\nNO FIRST AUDIO received within window")
    print(f"Audio total sent duration:      {len(data) * phrases / sr:.2f}s")


asyncio.run(main())
