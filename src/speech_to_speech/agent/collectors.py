"""s2s-agent 采集器：纯函数，可单测（spec 2026-11-17 §5.2/§5.3）。

与 console 的耦合只有约定（行格式、/v1/usage 的累计值语义），没有 import：
agent 独立跑在 pipeline 容器里，不依赖 console 代码。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

# 与 console `app.services.turn_latency_indexer.PREFIX` 同源——改这里必须同步改那里。
TURN_LATENCY_PREFIX = "TURN_LATENCY "

_LINE_TS = re.compile(
    r"^\[?(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:Z|[+-]\d{2}:?\d{2})?)"
)

# 单轮最多解析行数：与 console 索引器同口径，defer 不 drop。
MAX_LINES_PER_TICK = 2000


@dataclass
class Usage:
    """`/v1/usage` 的累计值快照（agent 差分的输入）。"""

    input_tokens: int = 0
    output_tokens: int = 0
    responses: int = 0
    audio_duration_s: float = 0.0
    window_s: int = 0


@dataclass
class UsageDelta:
    """窗口增量（心跳体 tokens{} 的内容）。"""

    input_tokens: int = 0
    output_tokens: int = 0
    responses: int = 0
    audio_duration_s: float = 0.0
    window_s: int = 0


def _delta(prev_value: float | int | None, cur_value: float | int) -> float | int:
    """累计值变小 = 计数器重置：本窗增量按累计值计（§5.3.4）。"""
    if prev_value is None or cur_value < prev_value:
        return cur_value
    return cur_value - prev_value


def usage_diff(prev: Usage | None, cur: Usage) -> UsageDelta:
    return UsageDelta(
        input_tokens=int(_delta(prev.input_tokens if prev else None, cur.input_tokens)),
        output_tokens=int(_delta(prev.output_tokens if prev else None, cur.output_tokens)),
        responses=int(_delta(prev.responses if prev else None, cur.responses)),
        audio_duration_s=float(_delta(prev.audio_duration_s if prev else None, cur.audio_duration_s)),
        window_s=cur.window_s,
    )


def _parse_ts(value: str) -> datetime | None:
    text = value.strip()
    if not text:
        return None
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text.replace(",", "."))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _to_ms(seconds: object) -> int | None:
    if seconds is None:
        return None
    try:
        return int(round(float(seconds) * 1000))
    except (TypeError, ValueError):
        return None


def _parse_line(text: str, logged_at: datetime) -> dict | None:
    """与 console `turn_latency_indexer.parse_line` 同一解析规则；另带 audio_duration_s。"""
    index = text.find(TURN_LATENCY_PREFIX)
    if index == -1:
        return None
    try:
        payload = json.loads(text[index + len(TURN_LATENCY_PREFIX) :])
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict) or not payload.get("response_key"):
        return None
    return {
        "response_key": str(payload["response_key"]),
        "turn_revision": int(payload.get("turn_revision") or 0),
        "turn_id": payload.get("turn_id"),
        "source": payload.get("source") or "",
        "status": payload.get("status") or "",
        "smart_status": payload.get("smart_status"),
        "e2e_ms": _to_ms(payload.get("e2e_s")),
        "stt_ms": _to_ms(payload.get("stt_s")),
        "llm_ms": _to_ms(payload.get("llm_s")),
        "tts_ttfa_ms": _to_ms(payload.get("tts_ttfa_s")),
        "vad_decision_ms": _to_ms(payload.get("vad_decision_s")),
        "hold_ms": _to_ms(payload.get("hold_s")),
        "audio_duration_s": payload.get("audio_duration_s"),
        # agent 上报行没有本机日志字节偏移语义（§7.1 边界 2），console 侧恒置 0。
        "logged_at": logged_at,
    }


def _pipeline_port(settings: "object | None" = None) -> int:
    """本机 pipeline 端口：声明文件优先，缺省 8765。"""
    try:  # noqa: SIM105 - 缺文件/坏文件都用默认端口
        import yaml  # noqa: PLC0415

        payload = yaml.safe_load(
            Path(getattr(settings, "declaration_file", "/app/config/agent.yaml")).read_text(
                encoding="utf-8"
            )
        )
        if isinstance(payload, dict) and payload.get("pipeline_port"):
            return int(payload["pipeline_port"])
    except Exception:
        pass
    return 8765


def read_usage(settings=None) -> Usage:
    """读本机 pipeline `GET /v1/usage` 的累计值（差分输入；不可达 → 零增量）。"""
    import httpx  # noqa: PLC0415 - 只在采集时需要

    try:
        response = httpx.get(
            f"http://127.0.0.1:{_pipeline_port(settings)}/v1/usage", timeout=3.0
        )
        response.raise_for_status()
        payload = response.json()
    except Exception:  # noqa: BLE001 - pipeline 不在：增量记零，不阻塞心跳
        return Usage()
    return Usage(
        input_tokens=int(payload.get("input_tokens") or 0),
        output_tokens=int(payload.get("output_tokens") or 0),
        responses=int(payload.get("responses") or 0),
        audio_duration_s=float(payload.get("audio_duration_s") or 0.0),
        window_s=int(payload.get("window_s") or 0),
    )


def collect_workloads(settings=None) -> list[dict]:
    """负载清单：agent.yaml 声明全量保留；pipeline 负载由探测 /v1/pool 补全（§5.3.3）。"""
    workloads: list[dict] = []
    declaration = Path(getattr(settings, "declaration_file", "/app/config/agent.yaml"))
    declared: list[dict] = []
    if declaration.is_file():
        try:
            import yaml  # noqa: PLC0415

            payload = yaml.safe_load(declaration.read_text(encoding="utf-8")) or {}
            declared = [item for item in (payload.get("workloads") or []) if isinstance(item, dict)]
        except Exception:  # noqa: BLE001 - 声明坏了就只剩探测
            declared = []
    for item in declared:
        workloads.append(
            {
                "kind": str(item.get("kind", "")),
                "engine": str(item.get("engine", "")),
                "model": str(item.get("model", "")),
                "port": item.get("port"),
                "vram_gb": item.get("vram_gb"),
                "health_path": str(item.get("health_path", "")),
                "health_interval_s": int(item.get("health_interval_s") or 30),
                "listen": str(item.get("listen", "")),
                "public_addr": str(item.get("public_addr", "")),
                "note": str(item.get("note", "")),
            }
        )

    if not any(item["kind"] == "pipeline" for item in workloads):
        port = _pipeline_port(settings)
        try:
            import httpx  # noqa: PLC0415

            httpx.get(f"http://127.0.0.1:{port}/v1/pool", timeout=2.0).raise_for_status()
        except Exception:  # noqa: BLE001 - 探测不到就不报 pipeline 负载
            return workloads
        workloads.append(
            {
                "kind": "pipeline",
                "engine": "speech-to-speech-pipeline",
                "model": "",
                "port": port,
                "vram_gb": None,
                "health_path": "/v1/pool",
                "health_interval_s": 5,
                "listen": f"127.0.0.1:{port}",
                "public_addr": f"127.0.0.1:{port}",
                "note": "会话 Pipeline（VAD · STT · LLM 调用 · TTS）",
            }
        )
    return workloads


def tail_turn_latency(path: str, since_offset: int) -> tuple[int, list[dict]]:
    """断点续读 `pipeline-stdout.log`，返回 (新 offset, 解析行)。

    offset 超界（文件轮转/截断）→ 回 0 重读，不抛错。
    """
    target = Path(path)
    if not target.is_file():
        return 0, []
    size = target.stat().st_size
    start = since_offset if 0 <= since_offset <= size else 0

    with target.open("rb") as handle:
        handle.seek(start)
        raw = handle.read()

    # 整行才解析：半写行等下一轮（与 console 索引器一致）。
    lines: list[tuple[int, str]] = []
    position = 0
    offset = start
    while len(lines) < MAX_LINES_PER_TICK:
        newline = raw.find(b"\n", position)
        if newline == -1:
            break
        lines.append((offset, raw[position:newline].decode("utf-8", "replace").rstrip("\r")))
        position = newline + 1
        offset = start + position

    fallback = datetime.fromtimestamp(target.stat().st_mtime, UTC)
    rows: list[dict] = []
    for _line_offset, text in lines:
        if TURN_LATENCY_PREFIX not in text:
            continue
        match = _LINE_TS.match(text)
        logged_at = _parse_ts(match.group(1)) if match else None
        row = _parse_line(text, logged_at or fallback)
        if row is not None:
            rows.append(row)
    return offset, rows
