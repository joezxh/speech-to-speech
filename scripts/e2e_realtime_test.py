#!/usr/bin/env python3
"""S2S (speech-to-speech) 端到端验证客户端。

用途
----
对本地/远端部署的 speech-to-speech Realtime 服务做一次完整链路体检：
    麦克风音频(16k PCM16) --> WS /v1/realtime --> STT --> LLM --> TTS --> 音频回传

它同时验证三件事：
  1. WS /v1/realtime 是否可用（S2S 主链路）
  2. STT 是否正确转写用户说了什么
  3. LLM + TTS 是否产出文本与音频，并给出 TTFA / 端到端延迟

用法
----
    # 在容器内跑（容器已装 websockets / soundfile / numpy）
    python3 scripts/e2e_realtime_test.py \
        --url ws://127.0.0.1:8765/v1/realtime \
        --audio /tmp/prompt.wav \
        --out-dir /tmp/e2e

    # 在宿主跑（需 websockets + soundfile + numpy）
    python scripts/e2e_realtime_test.py --url ws://127.0.0.1:8765/v1/realtime \
        --audio prompt.wav --out-dir ./e2e-out

事件序列（与 OpenAI Realtime 语义一致）：
    input_audio_buffer.append  x N   送入用户语音（16k PCM16 base64）
    input_audio_buffer.append 静音  尾部补静音，让服务端 VAD 收尾
    input_audio_buffer.commit       提交本轮 → 触发 STT
    (等待 conversation.item.input_audio_transcription.completed)
    response.create                 请求作答 → LLM → TTS
    (收集 response.audio.delta / response.audio_transcript.* / response.done)

退出码：0 = 全链路成功；1 = 失败（超时 / 无转写 / 无音频）。
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import sys
import time
from pathlib import Path

import numpy as np
import soundfile as sf

try:  # websockets >= 13 走 asyncio 实现
    from websockets.asyncio.client import connect
except ImportError:  # pragma: no cover - 老版本回退
    from websockets.client import connect


TARGET_SR = 16000


def load_pcm16(path: Path) -> bytes:
    """读任意音频 → 16k 单声道 PCM16 字节流。"""
    audio, sr = sf.read(str(path), dtype="float32", always_2d=False)
    if audio.ndim > 1:
        audio = audio.mean(axis=1)
    if sr != TARGET_SR:
        import librosa

        audio = librosa.resample(audio.astype(np.float32), orig_sr=sr, target_sr=TARGET_SR)
    pcm = (np.clip(audio, -1.0, 1.0) * 32767.0).astype(np.int16)
    return pcm.tobytes()


def silence(seconds: float) -> bytes:
    return (np.zeros(int(TARGET_SR * seconds), dtype=np.int16)).tobytes()


async def run(args: argparse.Namespace) -> int:
    pcm = load_pcm16(Path(args.audio))
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    url = args.url
    if url.startswith("http://"):
        url = "ws://" + url[len("http://") :]
    elif url.startswith("https://"):
        url = "wss://" + url[len("https://") :]
    if "/v1/realtime" not in url:
        url = url.rstrip("/") + "/v1/realtime"

    headers = {}
    if args.api_key:
        headers["Authorization"] = f"Bearer {args.api_key}"

    user_text: list[str] = []
    assistant_text: list[str] = []
    audio_chunks: list[bytes] = []
    errors: list[str] = []

    t0 = time.perf_counter()
    t_first_audio: float | None = None
    t_transcript: float | None = None

    async with connect(url, additional_headers=headers or None) as ws:
        # 1) 送入用户语音（分块，模拟实时流）
        chunk_bytes = args.chunk_bytes
        for i in range(0, len(pcm), chunk_bytes):
            await ws.send(
                json.dumps(
                    {
                        "type": "input_audio_buffer.append",
                        "audio": base64.b64encode(pcm[i : i + chunk_bytes]).decode(),
                    }
                )
            )
            await asyncio.sleep(args.chunk_delay)
        # 2) 尾部静音 → 让服务端 VAD 收尾
        await ws.send(
            json.dumps(
                {
                    "type": "input_audio_buffer.append",
                    "audio": base64.b64encode(silence(args.silence_ms / 1000.0)).decode(),
                }
            )
        )
        # 3) 是否显式提交
        #   auto（默认）= 不发 input_audio_buffer.commit，交由服务端 VAD 在检测到
        #   静音后自动提交（与真实浏览器客户端行为一致）；显式 commit 会与 VAD
        #   自动提交形成双重提交，导致服务端创建两个 response 而报
        #   "conversation_already_has_active_response"。
        #   always = 立即显式提交（服务端 VAD 未启用时使用）。
        if args.commit == "always":
            await ws.send(json.dumps({"type": "input_audio_buffer.commit"}))

        committed = False
        sent_response_create = False
        deadline = time.perf_counter() + args.timeout
        while time.perf_counter() < deadline:
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=max(0.1, deadline - time.perf_counter()))
            except asyncio.TimeoutError:
                break
            # 兜底：服务端在 VAD 判定静音后会自动创建 response；若迟迟没有产出，
            # 则显式补发一次 response.create（auto 模式）。
            if (
                args.response_create == "auto"
                and not sent_response_create
                and t_transcript is not None
                and not audio_chunks
                and (time.perf_counter() - t_transcript) > args.response_create_fallback
            ):
                sent_response_create = True
                await ws.send(json.dumps({"type": "response.create"}))
            try:
                evt = json.loads(raw)
            except (TypeError, ValueError):
                continue
            etype = evt.get("type", "")

            if etype == "error":
                errors.append(json.dumps(evt, ensure_ascii=False)[:400])
                continue
            if etype == "conversation.item.input_audio_transcription.completed":
                txt = evt.get("transcript") or ""
                if txt:
                    user_text.append(txt)
                if t_transcript is None:
                    t_transcript = time.perf_counter() - t0
                if args.response_create == "always" and not sent_response_create:
                    sent_response_create = True
                    await ws.send(json.dumps({"type": "response.create"}))
            elif etype == "response.audio.delta" or etype == "response.output_audio.delta":
                delta = evt.get("delta") or ""
                if delta:
                    if t_first_audio is None:
                        t_first_audio = time.perf_counter() - t0
                    audio_chunks.append(base64.b64decode(delta))
            elif etype in ("response.audio_transcript.delta", "response.output_audio_transcript.delta"):
                assistant_text.append(evt.get("delta") or "")
            elif etype in ("response.audio_transcript.completed", "response.output_audio_transcript.completed"):
                t = evt.get("transcript")
                if t:
                    assistant_text = [t]
            elif etype in ("response.done", "response.output_item.done", "response.output_items.done"):
                if etype == "response.done":
                    break
            elif etype == "conversation.item.input_audio_transcription.failed":
                errors.append("input transcription failed")

    total = time.perf_counter() - t0
    pcm_out = b"".join(audio_chunks)
    wav_path = out_dir / "assistant.wav"
    if pcm_out:
        sf.write(
            str(wav_path),
            np.frombuffer(pcm_out, dtype=np.int16).astype(np.float32) / 32768.0,
            TARGET_SR,
        )

    u_text = " ".join(t for t in user_text if t).strip()
    a_text = "".join(assistant_text).strip()

    print("=" * 68)
    print("S2S 端到端验证结果")
    print("=" * 68)
    print(f"  URL              : {url}")
    print(f"  输入音频         : {args.audio} ({len(pcm) / 2 / TARGET_SR:.2f}s @16k PCM16)")
    print(f"  用户转写 (STT)   : {u_text or '(空)'}")
    print(f"  助手回复 (LLM)   : {a_text or '(空)'}")
    print(f"  助手音频 (TTS)   : {len(pcm_out) / 2 / TARGET_SR:.2f}s / {len(pcm_out)} bytes")
    if t_transcript is not None:
        print(f"  STT 出字延迟     : {t_transcript:.2f}s")
    if t_first_audio is not None:
        print(f"  TTFA (首音)      : {t_first_audio:.2f}s")
    print(f"  端到端总耗时     : {total:.2f}s")
    if wav_path.exists():
        print(f"  音频输出文件     : {wav_path}")
    if errors:
        print("  错误事件         :")
        for e in errors[:5]:
            print(f"    - {e}")

    ok = bool(u_text) and bool(pcm_out)
    print("=" * 68)
    print(f"结论: {'✅ 全链路成功' if ok else '❌ 失败（缺转写或缺音频）'}")
    return 0 if ok else 1


def main() -> None:
    ap = argparse.ArgumentParser(description="S2S realtime 端到端验证")
    ap.add_argument("--url", default="ws://127.0.0.1:8765/v1/realtime", help="Realtime WS 地址")
    ap.add_argument("--audio", required=True, help="输入音频路径（任意采样率，内部转 16k PCM16）")
    ap.add_argument("--out-dir", default="./e2e-out", help="输出目录")
    ap.add_argument("--api-key", default="", help="可选 Bearer 凭据")
    ap.add_argument("--silence-ms", type=int, default=1200, help="尾部补静音时长")
    ap.add_argument("--chunk-bytes", type=int, default=3200, help="每次 append 的字节数（3200B=100ms@16k）")
    ap.add_argument("--chunk-delay", type=float, default=0.05, help="每次 append 间隔（秒）")
    ap.add_argument("--timeout", type=float, default=60.0, help="总超时（秒）")
    ap.add_argument(
        "--commit",
        choices=("auto", "always"),
        default="auto",
        help="input_audio_buffer.commit 策略：auto=不发，由服务端 VAD 自动提交（默认）；always=显式提交",
    )
    ap.add_argument(
        "--response-create",
        choices=("auto", "never", "always"),
        default="auto",
        help="response.create 策略：auto=转写后无产出则兜底补发；never=完全不发；always=转写完成立即发",
    )
    ap.add_argument(
        "--response-create-fallback",
        type=float,
        default=5.0,
        help="auto 模式下，转写完成后等待多少秒仍无音频则补发 response.create",
    )
    args = ap.parse_args()
    sys.exit(asyncio.run(run(args)))


if __name__ == "__main__":
    main()
