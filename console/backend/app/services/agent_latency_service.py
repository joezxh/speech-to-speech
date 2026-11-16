"""A5：agent 逐轮 TURN_LATENCY 行上报（per-machine TTFT 的唯一来源，spec §5.3.5）。

落行约束（§7.1 边界 2）：machine_id=token 所指机器、instance_id 空、
raw_offset 恒 0、logged_at 取行内时间戳（解析规则与 turn_latency_indexer 一致）。
按 (response_key, turn_revision) upsert——cancelled → completed 合法二次上报。
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.repositories.turn_latency_repository import upsert_many
from app.services.turn_latency_indexer import _parse_ts

_MS_FIELDS = (
    "e2e_ms",
    "stt_ms",
    "llm_ms",
    "tts_ttfa_ms",
    "vad_decision_ms",
    "hold_ms",
)


def report_rows(db: Session, machine_id: str, rows: list[dict]) -> dict:
    prepared: list[dict] = []
    for row in rows:
        if not row.get("response_key"):
            continue
        logged_at = row.get("logged_at")
        if isinstance(logged_at, str):
            logged_at = _parse_ts(logged_at)
        entry = {
            "response_key": str(row["response_key"]),
            "turn_revision": int(row.get("turn_revision") or 0),
            "turn_id": row.get("turn_id"),
            "source": row.get("source") or "",
            "status": row.get("status") or "",
            "smart_status": row.get("smart_status"),
            "audio_duration_s": row.get("audio_duration_s"),
            "machine_id": machine_id,
            "instance_id": None,
            "raw_offset": 0,
            "logged_at": logged_at or datetime.now(UTC),
        }
        for field in _MS_FIELDS:
            entry[field] = row.get(field)
        prepared.append(entry)
    upsert_many(db, prepared)
    return {"accepted": True, "count": len(prepared)}
