"""Temporary benchmark: emotion2vec_plus_large CPU container on this host.

Direct to 127.0.0.1:8021 (no nginx / no API key). Audio is synthesized in
memory and never written to disk.
"""
from __future__ import annotations

import io
import json
import os
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import httpx
import numpy as np
import soundfile as sf

URL = os.environ.get("SER_BENCH_URL", "http://127.0.0.1:8021/v1/audio/emotion")
CONTAINER = os.environ.get("SER_BENCH_CONTAINER", "emotion2vec")
PLAN = json.loads(os.environ.get("SER_BENCH_PLAN", "[[1,4],[3,4],[10,4],[30,2],[60,1]]"))
RNG = np.random.default_rng(20261115)
CPU_SAMPLES: list[float] = []


def wav_bytes(seconds: float) -> bytes:
    count = int(16000 * seconds)
    t = np.arange(count) / 16000
    signal = 0.12 * np.sin(2 * np.pi * 220 * t) + 0.04 * RNG.standard_normal(count)
    buffer = io.BytesIO()
    sf.write(buffer, signal.astype(np.float32), 16000, format="WAV")
    return buffer.getvalue()


def once(client: httpx.Client, wav: bytes) -> dict:
    started = time.perf_counter()
    response = client.post(
        URL,
        files={"file": ("bench.wav", wav, "audio/wav")},
        data={"sample_rate": "16000", "language": "zh"},
    )
    elapsed = (time.perf_counter() - started) * 1000
    body = response.json() if response.status_code == 200 else {}
    return {
        "status": response.status_code,
        "client_ms": round(elapsed, 1),
        "server_ms": body.get("latencyMs"),
        "emotion": body.get("emotion"),
        "detail": response.text[:160] if response.status_code != 200 else None,
    }


def percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, int(round((len(ordered) - 1) * p)))
    return round(ordered[index], 1)


def sample_cpu(stop: threading.Event) -> None:
    while not stop.is_set():
        proc = subprocess.run(
            ["docker", "stats", "--no-stream", "--format", "{{.CPUPerc}}", CONTAINER],
            capture_output=True,
            text=True,
        )
        try:
            CPU_SAMPLES.append(float(proc.stdout.strip().rstrip("%")))
        except ValueError:
            pass
        stop.wait(0.8)


def main() -> None:
    stop = threading.Event()
    sampler = threading.Thread(target=sample_cpu, args=(stop,), daemon=True)
    sampler.start()
    report: dict = {}
    try:
        with httpx.Client(timeout=180) as client:
            for seconds, rounds in PLAN:
                wav = wav_bytes(seconds)
                once(client, wav)  # per-length warm-up, not counted
                samples = [once(client, wav) for _ in range(rounds)]
                ok = [s for s in samples if s["status"] == 200]
                latency = [s["client_ms"] for s in ok]
                p50 = percentile(latency, 0.5)
                row = {
                    "rounds": rounds,
                    "ok": len(ok),
                    "failures": [s for s in samples if s["status"] != 200],
                    "p50_ms": p50,
                    "p95_ms": percentile(latency, 0.95),
                    "min_ms": round(min(latency), 1) if latency else None,
                    "max_ms": round(max(latency), 1) if latency else None,
                    "server_p50_ms": percentile(
                        [s["server_ms"] for s in ok if s["server_ms"] is not None], 0.5
                    ),
                    "rtf": round(p50 / 1000 / seconds, 4) if p50 else None,
                    "realtime_x": round(seconds * 1000 / p50, 2) if p50 else None,
                    "rps": round(1000 / p50, 3) if p50 else None,
                }
                report[f"{seconds}s"] = row
                print(f"{seconds}s {json.dumps(row, ensure_ascii=False)}", flush=True)

            wav = wav_bytes(3)
            started = time.perf_counter()
            with ThreadPoolExecutor(max_workers=2) as pool:
                concurrent = list(pool.map(lambda _: once(client, wav), range(8)))
            total = time.perf_counter() - started
            report["concurrency_2x8_3s"] = {
                "wall_s": round(total, 2),
                "ok": sum(1 for s in concurrent if s["status"] == 200),
                "statuses": [s["status"] for s in concurrent],
                "effective_rps": round(8 / total, 3),
            }
            print(
                f"concurrency {json.dumps(report['concurrency_2x8_3s'], ensure_ascii=False)}",
                flush=True,
            )
    finally:
        stop.set()
        sampler.join(timeout=2)

    report["container_cpu_peak_pct"] = round(max(CPU_SAMPLES), 1) if CPU_SAMPLES else None
    print("RESULT_JSON " + json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
