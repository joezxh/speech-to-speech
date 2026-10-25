"""A.17: the read side of the turn-latency index, plus the prompt block A.16 uses.

Two things this module refuses to do:

* invent a number. A stage with no measurement is `null`, and `hold` counts how
  many rows had no measurement instead of averaging them in as 0 (§3.9.4);
* hide data because the index is behind. `index_lag` labels the aggregate as
  "not the present" while still returning the rows it has.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.config import console as console_settings
from app.models.turn_latency import TurnLatencyRow
from app.repositories import turn_latency_repository as repo
from app.schemas.common import iso_utc
from app.schemas.turn_latency import (
    DEFAULT_WINDOW_MINUTES,
    LAG_LIMIT_S,
    MAX_AGGREGATE_ROWS,
    MAX_WINDOW_HOURS,
    STATUSES,
)

# The index is built from the pipeline's own supervisor logs; when neither file
# exists there is nothing to rebuild from, which is `log_missing`, not "0 turns".
INDEX_SOURCES = ("pipeline-stdout.log", "pipeline-stderr.log")


def _parse_ts(value: str | None) -> datetime | None:
    text = (value or "").strip()
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


def resolve_window(
    from_iso: str | None, to_iso: str | None, *, now: datetime | None = None
) -> tuple[datetime, datetime]:
    """A.17's rule: 15 minutes by default, 24 hours at most."""
    end = _parse_ts(to_iso) if to_iso else (now or datetime.now(UTC))
    if end is None:
        raise ValueError("to must be an ISO 8601 timestamp")
    start = _parse_ts(from_iso) if from_iso else end - timedelta(minutes=DEFAULT_WINDOW_MINUTES)
    if start is None:
        raise ValueError("from must be an ISO 8601 timestamp")
    if start > end:
        raise ValueError("from must not be after to")
    if end - start > timedelta(hours=MAX_WINDOW_HOURS):
        raise ValueError(f"the window is capped at {MAX_WINDOW_HOURS} hours")
    return start, end


def _stage(values: list[int]) -> dict[str, int | None]:
    return {"p50Ms": repo.percentile(values, 0.5), "p95Ms": repo.percentile(values, 0.95)}


def _values(rows: list[TurnLatencyRow], attribute: str) -> list[int]:
    return [value for row in rows if (value := getattr(row, attribute)) is not None]


def summarise(rows: list[TurnLatencyRow], total: int) -> dict[str, Any]:
    """State counts and percentiles over the rows we actually hold.

    `count` is the window's true count, so it can exceed the sum of the four
    states when `truncated` is true — which is exactly what `truncated` is for.
    """
    states = {name: sum(1 for row in rows if row.status == name) for name in STATUSES}
    e2e = _values(rows, "e2e_ms")
    hold_values = _values(rows, "hold_ms")
    stages = {
        "stt": _stage(_values(rows, "stt_ms")),
        "llm": _stage(_values(rows, "llm_ms")),
        "ttsTtfa": _stage(_values(rows, "tts_ttfa_ms")),
        "vadDecision": _stage(_values(rows, "vad_decision_ms")),
        "hold": {
            **_stage(hold_values),
            # A `null` hold is "not measured", never "waited 0 ms".
            "unavailableCount": sum(1 for row in rows if row.hold_ms is None),
        },
    }
    return {
        "count": total,
        "completed": states["completed"],
        "failed": states["failed"],
        "cancelled": states["cancelled"],
        "incomplete": states["incomplete"],
        "failureRate": round(states["failed"] / total, 4) if total else None,
        "e2e": {**_stage(e2e), "maxMs": max(e2e) if e2e else None},
        "stages": stages,
    }


def summary_reason(summary: dict[str, Any], index: dict[str, Any]) -> str | None:
    """The most upstream reason only (A.17): downstream causes are its effects."""
    if not index["sources"]:
        return "log_missing"
    if index["lagS"] is None:
        return "indexer_never_ran"
    if index["lagS"] > LAG_LIMIT_S:
        return "index_lag"
    if summary["count"] == 0:
        return "no_turn_rows"
    return None


def _sources(log_dir: str | Path) -> list[dict[str, Any]]:
    root = Path(log_dir)
    entries: list[dict[str, Any]] = []
    for name in INDEX_SOURCES:
        path = root / name
        try:
            stat = path.stat()
        except OSError:
            continue
        entries.append(
            {
                "file": name,
                "size": int(stat.st_size),
                "mtime": iso_utc(datetime.fromtimestamp(stat.st_mtime, UTC)),
            }
        )
    return entries


def _index(session: Session, now: datetime) -> dict[str, Any]:
    ingested = repo.latest_ingested_at(session)
    if ingested is None:
        lag: int | None = None
    else:
        if ingested.tzinfo is None:
            ingested = ingested.replace(tzinfo=UTC)
        lag = max(0, int((now - ingested).total_seconds()))
    return {
        "lagS": lag,
        "ingestedAt": iso_utc(ingested),
        "sources": _sources(console_settings.log_dir),
    }


def _item(row: TurnLatencyRow) -> dict[str, Any]:
    return {
        "loggedAt": iso_utc(row.logged_at) or "",
        "responseKey": row.response_key,
        "turnRevision": int(row.turn_revision or 0),
        "source": row.source or "",
        "status": row.status or "",
        "smartStatus": row.smart_status,
        "e2eMs": row.e2e_ms,
        "sttMs": row.stt_ms,
        "llmMs": row.llm_ms,
        "ttsTtfaMs": row.tts_ttfa_ms,
        "vadDecisionMs": row.vad_decision_ms,
        "holdMs": row.hold_ms,
    }


def read(
    session: Session,
    *,
    start: datetime,
    end: datetime,
    status: list[str] | None = None,
    limit: int = 100,
    now: datetime | None = None,
) -> dict[str, Any]:
    """A.17's `data`. Aggregation happens in memory over ≤ 2000 rows."""
    moment = now or datetime.now(UTC)
    wanted = [name for name in (status or []) if name in STATUSES]
    total = repo.count_in_window(session, start=start, end=end, status=wanted)
    fetched = repo.fetch(
        session, start=start, end=end, status=wanted, limit=MAX_AGGREGATE_ROWS
    )
    summary = summarise(fetched, total)
    index = _index(session, moment)
    reason = summary_reason(summary, index)
    return {
        "window": {
            "from": iso_utc(start),
            "to": iso_utc(end),
        },
        "summary": summary,
        "rows": [_item(row) for row in fetched[: max(0, limit)]],
        "truncated": total > MAX_AGGREGATE_ROWS,
        "index": index,
        "reasons": {"summary": reason} if reason else {},
    }


TURN_PROMPT = """## 轮次摘要（与上面同一时间窗，共 {count} 条）
状态：completed {completed} / failed {failed} / cancelled {cancelled} / incomplete {incomplete}，failureRate {failure_rate}
e2e：p50 {e2e_p50} / p95 {e2e_p95} / max {e2e_max}
stt：p50 {stt_p50} / p95 {stt_p95}
llm：p50 {llm_p50} / p95 {llm_p95}
ttsTtfa：p50 {tts_p50} / p95 {tts_p95}
vadDecision：p50 {vad_p50} / p95 {vad_p95}
hold：p50 {hold_p50} / p95 {hold_p95}（{hold_missing} 条未测到）
若附带了轮次摘要，必须回答「慢在哪一段」，并区分「浏览器播放慢」与「服务端慢」。
数值缺失写 unavailable，不要当 0；各段互相重叠，不可相加。
"""


def _ms(value: int | None) -> str:
    return "unavailable" if value is None else f"{value} ms"


def prompt_block(
    start: datetime,
    end: datetime,
    *,
    enabled: bool = True,
    summary: dict[str, Any] | None = None,
    session: Session | None = None,
) -> tuple[str, int]:
    """The aggregate paragraph A.16 appends, and how many turns it covers.

    Best-effort by design: a broken index must degrade the analysis, not fail it.
    """
    if not enabled:
        return "", 0
    try:
        if summary is None:
            if session is not None:
                summary = read(session, start=start, end=end, limit=0)["summary"]
            else:
                from app.db.database import SessionLocal  # noqa: PLC0415

                with SessionLocal() as own:
                    summary = read(own, start=start, end=end, limit=0)["summary"]
    except Exception:  # noqa: BLE001 - the log analysis still has value without it
        return "", 0
    if not summary or not summary.get("count"):
        return "", 0
    stages = summary["stages"]
    e2e = summary["e2e"]
    block = TURN_PROMPT.format(
        count=summary["count"],
        completed=summary["completed"],
        failed=summary["failed"],
        cancelled=summary["cancelled"],
        incomplete=summary["incomplete"],
        failure_rate="unavailable" if summary["failureRate"] is None else summary["failureRate"],
        e2e_p50=_ms(e2e["p50Ms"]),
        e2e_p95=_ms(e2e["p95Ms"]),
        e2e_max=_ms(e2e["maxMs"]),
        stt_p50=_ms(stages["stt"]["p50Ms"]),
        stt_p95=_ms(stages["stt"]["p95Ms"]),
        llm_p50=_ms(stages["llm"]["p50Ms"]),
        llm_p95=_ms(stages["llm"]["p95Ms"]),
        tts_p50=_ms(stages["ttsTtfa"]["p50Ms"]),
        tts_p95=_ms(stages["ttsTtfa"]["p95Ms"]),
        vad_p50=_ms(stages["vadDecision"]["p50Ms"]),
        vad_p95=_ms(stages["vadDecision"]["p95Ms"]),
        hold_p50=_ms(stages["hold"]["p50Ms"]),
        hold_p95=_ms(stages["hold"]["p95Ms"]),
        hold_missing=stages["hold"]["unavailableCount"],
    )
    return block, int(summary["count"])
