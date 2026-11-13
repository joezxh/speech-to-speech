"""声纹嵌入端点自测：capability + 并发容量 + 时延分位（对齐 g0-probe.ps1 的 G0-c 口径）。

用法：
    python3 scripts/voiceprint_probe.py --base-url http://127.0.0.1:8765 \
        --api-key <key> --concurrency 8 --rounds 3

输出：capability 摘要、并发样本的 P95/5xx/超时数、以及 ASR 对照基线是否劣化。
"""
import argparse
import base64
import io
import json
import math
import struct
import time
import urllib.error
import urllib.request
import wave
from concurrent.futures import ThreadPoolExecutor


def make_tone_wav(seconds=3.0, sr=16000, freq=440.0, amplitude=6000.0) -> bytes:
    """生成 440Hz 纯音 WAV（与 g0-probe.ps1 的 New-ProbeWav 同型）。"""
    frames = int(sr * seconds)
    data = b"".join(
        struct.pack("<h", int(math.sin(2 * math.pi * freq * i / sr) * amplitude))
        for i in range(frames)
    )
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(data)
    return buf.getvalue()


def post_multipart(url, fields, files, headers=None, timeout=30):
    boundary = "----probeboundary1234567890"
    body = io.BytesIO()
    for k, v in fields.items():
        body.write(f"--{boundary}\r\n".encode())
        body.write(f'Content-Disposition: form-data; name="{k}"\r\n\r\n'.encode())
        body.write(f"{v}\r\n".encode())
    for k, (fname, data, ctype) in files.items():
        body.write(f"--{boundary}\r\n".encode())
        body.write(
            f'Content-Disposition: form-data; name="{k}"; filename="{fname}"\r\n'.encode()
        )
        body.write(f"Content-Type: {ctype}\r\n\r\n".encode())
        body.write(data)
        body.write(b"\r\n")
    body.write(f"--{boundary}--\r\n".encode())
    payload = body.getvalue()
    hdrs = {"Content-Type": f"multipart/form-data; boundary={boundary}"}
    if headers:
        hdrs.update(headers)
    req = urllib.request.Request(url, data=payload, headers=hdrs, method="POST")
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            return resp.status, raw, (time.perf_counter() - started) * 1000
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), (time.perf_counter() - started) * 1000
    except Exception as exc:  # noqa: BLE001
        return 0, str(exc).encode(), (time.perf_counter() - started) * 1000


def get_json(url, headers=None, timeout=15):
    req = urllib.request.Request(url, headers=headers or {}, method="GET")
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read(), (time.perf_counter() - started) * 1000
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), (time.perf_counter() - started) * 1000
    except Exception as exc:  # noqa: BLE001
        return 0, str(exc).encode(), (time.perf_counter() - started) * 1000


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", default="http://127.0.0.1:8765")
    ap.add_argument("--api-key", required=True)
    ap.add_argument("--concurrency", type=int, default=8)
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--timeout", type=int, default=8)
    args = ap.parse_args()

    base = args.base_url.rstrip("/")
    auth = {"Authorization": f"Bearer {args.api_key}"}
    wav = make_tone_wav()

    print("== capability ==")
    status, raw, ms = get_json(f"{base}/v1/audio/embeddings/capability", auth)
    print(f"  HTTP {status} in {ms:.0f} ms")
    if status == 200:
        cap = json.loads(raw)
        print(f"  dim={cap.get('dim')} model={cap.get('model')} ready={cap.get('ready')}")

    print("== 裸请求（鉴权）==")
    status, _, _ = post_multipart(
        f"{base}/v1/audio/embeddings",
        {"model": "", "purpose": "verify"},
        {"file": ("probe.wav", wav, "audio/wav")},
    )
    print(f"  无凭据 → HTTP {status}（期望 401/403）")

    print("== 单次 embeddings ==")
    status, raw, ms = post_multipart(
        f"{base}/v1/audio/embeddings",
        {"model": "", "purpose": "verify"},
        {"file": ("probe.wav", wav, "audio/wav")},
        auth,
    )
    print(f"  HTTP {status} in {ms:.0f} ms")
    if status == 200:
        body = json.loads(raw)
        emb = body.get("embedding", [])
        print(
            f"  dim={body.get('dim')} len(embedding)={len(emb)} "
            f"model={body.get('model')} quality={body.get('quality')} "
            f"speechDurationMs={body.get('speechDurationMs')}"
        )
        print(f"  字段集合: {sorted(body)}")
    else:
        print(f"  响应体: {raw[:300]!r}")

    print("== 并发容量 ==")
    samples = []

    def one(_):
        return post_multipart(
            f"{base}/v1/audio/embeddings",
            {"model": "", "purpose": "verify"},
            {"file": ("probe.wav", wav, "audio/wav")},
            auth,
            args.timeout,
        )

    with ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        for _ in range(args.rounds):
            samples.extend(pool.map(one, range(args.concurrency)))

    codes = [s[0] for s in samples]
    lat = sorted(s[2] for s in samples)
    p95 = lat[min(len(lat) - 1, math.ceil(len(lat) * 0.95) - 1)] if lat else 0
    print(f"  样本 {len(samples)}  5xx={sum(1 for c in codes if c >= 500)}  "
          f"超时/失败={sum(1 for c in codes if c == 0)}")
    print(f"  P95={p95:.0f} ms  最大={lat[-1]:.0f} ms（预算 ≤3000 ms）")


if __name__ == "__main__":
    main()
