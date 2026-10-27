"""Model runtime snapshot for the instance page (A.14).

Read-only bypass. Four sources, each one optional, each one read in a worker
thread: a missing source becomes a `reasons` code — never a zero, never a blank
cell, and never a 5xx. The page is at its most useful exactly when the pipeline
is *not* healthy.

Cost is constant by design: the console runs one worker inside the same
container as the pipeline, so a snapshot may only read 256 KiB of one log tail,
run `nvidia-smi` once and call `/v1/pool` once. No full-file scans, no writes.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import shutil
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.config import console
from app.schemas.common import iso_utc
from app.services import pool, process_probe

logger = logging.getLogger(__name__)

# Fixed order, and it is the order the cards render in (A.14).
STAGES = ("vad", "stt", "llm", "tts")

# The monitor writes uppercase categories (`CallRecord.category`).
CATEGORY = {"stt": "STT", "llm": "LLM", "tts": "TTS"}

# Cross-process contract with `speech_to_speech.utils.model_monitor`: the
# console image does not import that package, so the marker is repeated here.
MARKER = "MODEL_CALL_METRICS"

TAIL_BYTES = 256 * 1024
GPU_QUERY = ("--query-gpu=name,memory.total,memory.used", "--format=csv,noheader,nounits")
VRAM_PRESSURE_PERCENT = 90.0

_TTL_S = 3.0
_TIMEOUT_S = 2.0
_cache: dict[tuple[str, int], tuple[float, dict[str, Any]]] = {}


def invalidate() -> None:
    """Drop the cached frame: a publish changes what the cards should say."""
    _cache.clear()


def collect(profile: str, window_s: int = 300) -> dict[str, Any]:
    """A.14's `data`, or the previous frame plus `runtime_degraded`."""
    now = time.monotonic()
    cached = _cache.get((profile, window_s))
    if cached and now - cached[0] < _TTL_S:
        return cached[1]

    try:
        data = asyncio.run(_collect_async(profile, window_s))
    except TimeoutError:
        data = _degraded(profile, window_s, cached, "snapshot budget exhausted")
    except Exception as exc:  # noqa: BLE001 - a snapshot must not become a 500
        logger.warning("runtime snapshot failed for {}: {}", profile, exc)
        data = _degraded(profile, window_s, cached, str(exc))

    _cache[(profile, window_s)] = (time.monotonic(), data)
    return data


def _degraded(
    profile: str,
    window_s: int,
    cached: tuple[float, dict[str, Any]] | None,
    why: str,
) -> dict[str, Any]:
    """Previous frame (stale but real) or an all-reasons frame, plus the alert."""
    logger.warning("runtime snapshot degraded ({}): {}", profile, why)
    upstream = cached[1] if cached else _empty(profile, window_s)
    return {**upstream, "alerts": sorted({*upstream.get("alerts", ()), "runtime_degraded"})}


async def _collect_async(profile: str, window_s: int) -> dict[str, Any]:
    gathered = asyncio.gather(
        asyncio.to_thread(_gpu),
        asyncio.to_thread(_metrics_tail, window_s=window_s),
        asyncio.to_thread(_pool),
        asyncio.to_thread(_pipeline_running),
        return_exceptions=True,
    )
    gpu, lines, pool_state, running = await asyncio.wait_for(gathered, _TIMEOUT_S)

    # `return_exceptions=True` keeps one dead source from taking the other three
    # with it; each fallback here is the same value the source would have
    # reported on its own failure.
    if not isinstance(gpu, dict):
        gpu = {"available": False, "reason": "nvidia_smi_missing"}
    if not isinstance(lines, list):
        lines = []
    if not isinstance(pool_state, pool.PoolState):
        pool_state = pool.PoolState(reachable=False, error=str(pool_state))
    if not isinstance(running, bool):
        running = True

    return _build(profile, window_s, gpu, lines, pool_state, running)


def _build(
    profile: str,
    window_s: int,
    gpu: dict[str, Any],
    lines: list[str],
    pool_state: pool.PoolState,
    running: bool,
) -> dict[str, Any]:
    records = _records(lines)
    stages = [_stage(name, records, gpu, pool_state, running) for name in STAGES]
    return {
        "profile": profile,
        "collectedAt": iso_utc(datetime.now(UTC)),
        "windowS": window_s,
        "gpu": gpu,
        "stages": stages,
        "alerts": _alerts(stages, gpu, pool_state, running),
    }


def _stage(
    stage: str,
    records: list[dict[str, Any]],
    gpu: dict[str, Any],
    pool_state: pool.PoolState,
    running: bool,
) -> dict[str, Any]:
    category = CATEGORY.get(stage)
    mine = [r for r in records if r.get("category") == category] if category else []
    latest = mine[-1] if mine else None
    reasons: dict[str, str] = {}

    loaded, loaded_reason = _loaded(stage, latest, running)
    if loaded_reason:
        reasons["loaded"] = loaded_reason

    used_mb, percent, vram_reason = _vram(latest, gpu, running)
    if vram_reason:
        reasons["vram"] = vram_reason

    in_use, size, busy_reason = _busy(pool_state)
    if busy_reason:
        reasons["busy"] = busy_reason

    # No source exposes a per-stage queue depth in this pipeline, so the field
    # is `null` by definition — not `0`, which would read as "empty".
    reasons["queueDepth"] = "queue_depth_not_exposed"

    first_byte_ms, first_byte_reason = _first_byte(stage, latest, running)
    if first_byte_reason:
        reasons["firstByte"] = first_byte_reason

    process_ms, p50_ms, p95_ms, latency_reason = _latency(mine, running)
    if latency_reason:
        reasons["latency"] = latency_reason

    return {
        "stage": stage,
        "modelName": _text(latest.get("model_name")) if latest else None,
        "backend": _backend(latest),
        "loaded": loaded,
        "vram": {"usedMb": used_mb, "percent": percent},
        "busy": {"inUse": in_use, "size": size, "occupied": bool(in_use), "queueDepth": None},
        "latency": {
            "firstByteMs": first_byte_ms,
            "processMs": process_ms,
            "p50Ms": p50_ms,
            "p95Ms": p95_ms,
        },
        "reasons": reasons,
    }


def _loaded(stage: str, latest: dict[str, Any] | None, running: bool) -> tuple[bool, str]:
    if not running:
        return False, "pipeline_stopped"
    # The pipeline loads its models at startup and keeps them resident, so a
    # running process is the honest evidence that the stage is available — VAD,
    # STT, LLM and TTS alike. Requiring a recent per-category call would brand
    # STT and the remote LLM "not loaded" forever: the deployed qwen3-asr and
    # chat-completions handlers emit no MODEL_CALL_METRICS at all (see
    # docs/upstream-diff-and-deployment-config.md §2.7). Metrics only *enrich*
    # the name / VRAM / latency cells; their absence is reported there, never
    # as a red card over a pipeline that is serving fine.
    return True, ""


def _vram(
    latest: dict[str, Any] | None, gpu: dict[str, Any], running: bool
) -> tuple[int | None, float | None, str]:
    """`resources.vram_used_mb_peak` is the *whole card's* peak during the call.

    Without a total we cannot express it as a fraction, and a bare number on
    four cards reads as "this stage alone uses 18 GB" — which is false, since
    all four stages share the same device. So an unavailable GPU hides the
    number rather than mis-attributing it.
    """
    if not gpu.get("available"):
        return None, None, str(gpu.get("reason") or "nvidia_smi_missing")
    if latest is None:
        return None, None, _window_reason(running)
    measured = _number((latest.get("resources") or {}).get("vram_used_mb_peak"))
    if measured is None:
        return None, None, "vram_not_attributable"
    used_mb = int(round(measured))
    total_mb = _number(gpu.get("totalMb"))
    percent = round(used_mb / total_mb * 100, 1) if total_mb else None
    return used_mb, percent, ""


def _busy(pool_state: pool.PoolState) -> tuple[int | None, int | None, str]:
    if not pool_state.reachable:
        return None, None, "pool_unreachable"
    return pool_state.in_use, pool_state.size, ""


def _first_byte(
    stage: str, latest: dict[str, Any] | None, running: bool
) -> tuple[int | None, str]:
    if stage == "vad":
        # Not "not measured": a VAD decision has no first byte to wait for.
        return None, "not_applicable"
    if latest is None:
        return None, _window_reason(running)
    seconds = _number((latest.get("output") or {}).get("first_byte_s"))
    if seconds is None:
        # STT is the visible case: its handler never marks the boundary.
        return None, "first_byte_not_instrumented"
    return int(round(seconds * 1000)), ""


def _latency(
    mine: list[dict[str, Any]], running: bool
) -> tuple[int | None, int | None, int | None, str]:
    durations = [value for value in (_number(r.get("duration_s")) for r in mine) if value is not None]
    if not durations:
        return None, None, None, _window_reason(running)
    return (
        int(round(durations[-1] * 1000)),
        int(round(_percentile(durations, 50) or 0)),
        int(round(_percentile(durations, 95) or 0)),
        "",
    )


def _window_reason(running: bool) -> str:
    return "no_metrics_window" if running else "pipeline_stopped"


def _alerts(
    stages: list[dict[str, Any]],
    gpu: dict[str, Any],
    pool_state: pool.PoolState,
    running: bool,
) -> list[str]:
    alerts: list[str] = []
    if not running:
        alerts.append("pipeline_stopped")
    if not pool_state.reachable:
        alerts.append("pool_unreachable")
    if gpu.get("available") and any(
        (stage["vram"]["percent"] or 0.0) >= VRAM_PRESSURE_PERCENT for stage in stages
    ):
        alerts.append("vram_pressure")
    return alerts


def _empty(profile: str, window_s: int) -> dict[str, Any]:
    """No frame to fall back to: every card says why it knows nothing."""
    gpu = {"available": False, "reason": "nvidia_smi_missing"}
    stages = [
        {
            "stage": stage,
            "modelName": None,
            "backend": None,
            "loaded": False,
            "vram": {"usedMb": None, "percent": None},
            "busy": {"inUse": None, "size": None, "occupied": False, "queueDepth": None},
            "latency": {"firstByteMs": None, "processMs": None, "p50Ms": None, "p95Ms": None},
            "reasons": {
                "loaded": "pipeline_stopped",
                "vram": "nvidia_smi_missing",
                "busy": "pool_unreachable",
                "queueDepth": "queue_depth_not_exposed",
                "firstByte": "not_applicable" if stage == "vad" else "no_metrics_window",
                "latency": "no_metrics_window",
            },
        }
        for stage in STAGES
    ]
    return {
        "profile": profile,
        "collectedAt": iso_utc(datetime.now(UTC)),
        "windowS": window_s,
        "gpu": gpu,
        "stages": stages,
        "alerts": [],
    }


# -- the four sources ---------------------------------------------------------


def _gpu() -> dict[str, Any]:
    """A.14's one `nvidia-smi` call. Absent driver is a code, not an exception."""
    try:
        smi = shutil.which("nvidia-smi")
        if not smi:
            return {"available": False, "reason": "nvidia_smi_missing"}
        completed = subprocess.run(
            [smi, *GPU_QUERY], capture_output=True, text=True, timeout=2, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return {"available": False, "reason": "nvidia_smi_missing"}

    first = completed.stdout.strip().splitlines()
    parts = [part.strip() for part in first[0].split(",")] if first else []
    if len(parts) < 3:
        return {"available": False, "reason": "nvidia_smi_missing"}
    total = _number(parts[1])
    used = _number(parts[2])
    if total is None or used is None:
        return {"available": False, "reason": "nvidia_smi_missing"}
    return {
        "available": True,
        "name": parts[0] or None,
        "totalMb": int(total),
        "usedMb": int(used),
        "percent": round(used / total * 100, 1) if total else None,
    }


def _metrics_tail(*, window_s: int = 300) -> list[str]:
    """Raw `MODEL_CALL_METRICS` lines from the tail of the metrics log.

    Returns strings, not parsed records, so the parser (and its tests) sit in
    one place. The log rotates at 20 MB, so the tail of the live file is the
    only affordable read; older calls are simply outside the window.
    """
    path = Path(console.model_metrics_log)
    try:
        size = path.stat().st_size
        with path.open("rb") as handle:
            handle.seek(max(0, size - TAIL_BYTES))
            chunk = handle.read()
    except OSError:
        return []

    text = chunk.decode("utf-8", errors="replace")
    if size > TAIL_BYTES:
        # The first line starts mid-record; dropping it is the only safe cut.
        text = text.split("\n", 1)[-1]

    cutoff = _stamp(time.time() - window_s)
    kept: list[str] = []
    for line in text.splitlines():
        if MARKER not in line:
            continue
        stamped = _stamp_of(line)
        # A line we cannot date is kept: `_records` will reject it if it is not
        # JSON, and dropping datable-but-unreadable lines hides real calls.
        if stamped and stamped < cutoff:
            continue
        kept.append(line)
    return kept


def _pool() -> pool.PoolState:
    return pool.read_pool()


def _pipeline_running() -> bool:
    info = process_probe.get_probe().state(console.supervisor_program)
    # "Could not ask" (no socket — a local run) is not "stopped": claiming
    # stopped would paint four red cards over a pipeline that is serving fine.
    return not info.confirmed_stopped()


# -- parsing helpers ----------------------------------------------------------


def _records(lines: list[str]) -> list[dict[str, Any]]:
    """Parsed records, oldest first (the log is append-only)."""
    records: list[dict[str, Any]] = []
    for line in lines:
        at = line.find("{")
        if at < 0:
            continue
        try:
            payload = json.loads(line[at:])
        except ValueError:
            continue
        record = payload.get(MARKER) if isinstance(payload, dict) else None
        if isinstance(record, dict):
            records.append(record)
    return records


def _stamp_of(line: str) -> str:
    """`start_time` of a metrics line, or "" when the shape is unexpected."""
    head = '"start_time": "'
    at = line.find(head)
    if at < 0:
        return ""
    begin = at + len(head)
    end = line.find('"', begin)
    return line[begin:end] if end > begin else ""


def _stamp(epoch: float) -> str:
    """Same format as `CallRecord.to_dict()`, so the strings compare as times."""
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(epoch))


def _backend(latest: dict[str, Any] | None) -> str | None:
    payload = latest.get("input") if latest else None
    if not isinstance(payload, dict):
        return None
    return _text(payload.get("backend"))


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _number(value: Any) -> float | None:
    """A float, or None for anything JSON might legitimately carry instead."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _percentile(values: list[float], percent: float) -> float | None:
    """Nearest-rank: no interpolation, so p95 of one call is that call."""
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, min(len(ordered), math.ceil(percent / 100 * len(ordered))))
    return ordered[rank - 1]
