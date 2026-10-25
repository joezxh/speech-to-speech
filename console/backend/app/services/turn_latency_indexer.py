"""A.17's indexer: `pipeline-stdout.log` → `turn_latency`, every 5 s.

The cursor is `{inode, offset}`, the same shape A.15 uses and for the same
reason: rotation rewrites line numbers and keeps the file name, so an inode
change is the only reliable "this is a different file" signal.

The per-tick cap defers, it does not drop: after a burst the next tick continues
from the byte after the 2000th line. And one malformed line is counted, not
fatal — an indexer that stops on a truncated write stops exactly when the
pipeline is crashing, which is when the panel matters.
"""

from __future__ import annotations

import asyncio
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from loguru import logger
from sqlalchemy.orm import Session

from app.config import console as console_settings
from app.repositories.turn_latency_repository import to_ms, upsert_many

CURSOR_FILE = "turn_latency.cursor.json"
INTERVAL_S = 5.0
MAX_LINES_PER_TICK = 2000
TARGET = "pipeline-stdout.log"
PREFIX = "TURN_LATENCY "

_LINE_TS = re.compile(
    r"^\[?(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:Z|[+-]\d{2}:?\d{2})?)"
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


def parse_line(text: str, logged_at: datetime, raw_offset: int) -> dict | None:
    """Bad JSON or a missing primary key → `None` (counted, never fatal)."""
    index = text.find(PREFIX)
    if index == -1:
        return None
    try:
        payload = json.loads(text[index + len(PREFIX) :])
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
        # Seconds → milliseconds; `None` stays `None` (A.17's third boundary).
        "e2e_ms": to_ms(payload.get("e2e_s")),
        "stt_ms": to_ms(payload.get("stt_s")),
        "llm_ms": to_ms(payload.get("llm_s")),
        "tts_ttfa_ms": to_ms(payload.get("tts_ttfa_s")),
        "vad_decision_ms": to_ms(payload.get("vad_decision_s")),
        "hold_ms": to_ms(payload.get("hold_s")),
        "logged_at": logged_at,
        "raw_offset": raw_offset,
    }


def _cursor_path(data_dir: str | Path) -> Path:
    return Path(data_dir) / CURSOR_FILE


def _read_cursor(path: Path) -> dict[str, int] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    try:
        return {"inode": int(payload["inode"]), "offset": int(payload["offset"])}
    except (KeyError, TypeError, ValueError):
        return None


def _write_cursor(path: Path, inode: int, offset: int) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"inode": inode, "offset": offset}), encoding="utf-8")
    except OSError as exc:
        # The next tick re-reads from the old offset; a duplicate upsert is
        # harmless, a crash is not.
        logger.warning("turn latency cursor is not writable: {}", exc)


def _split(raw: bytes, start: int, limit: int) -> tuple[list[tuple[int, str]], int]:
    """Whole lines only: a half-written line waits for the next tick."""
    lines: list[tuple[int, str]] = []
    position = 0
    offset = start
    while len(lines) < limit:
        newline = raw.find(b"\n", position)
        if newline == -1:
            break
        chunk = raw[position:newline]
        lines.append((offset, chunk.decode("utf-8", "replace").rstrip("\r")))
        position = newline + 1
        offset = start + position
    return lines, offset


def ingest_once(
    session: Session,
    *,
    log_dir: str | Path,
    data_dir: str | Path,
    limit: int = MAX_LINES_PER_TICK,
) -> dict[str, Any]:
    """One tick. Returns the counters the panel's `index` block is built from."""
    target = Path(log_dir) / TARGET
    if not target.is_file():
        return {"ingested": 0, "skipped": 0, "reset": False, "offset": 0, "missing": True}

    stat = target.stat()
    inode = int(getattr(stat, "st_ino", 0))
    cursor_path = _cursor_path(data_dir)
    cursor = _read_cursor(cursor_path)

    start = 0
    reset = False
    if cursor is not None:
        if cursor["inode"] == inode and cursor["offset"] <= int(stat.st_size):
            start = cursor["offset"]
        else:
            reset = True

    with target.open("rb") as handle:
        handle.seek(start)
        raw = handle.read()

    lines, offset = _split(raw, start, limit)
    fallback = datetime.fromtimestamp(stat.st_mtime, UTC)

    rows: list[dict[str, Any]] = []
    skipped = 0
    for line_offset, text in lines:
        if PREFIX not in text:
            continue  # the human-readable line stays human-readable
        match = _LINE_TS.match(text)
        logged_at = _parse_ts(match.group(1)) if match else None
        row = parse_line(text, logged_at or fallback, line_offset)
        if row is None:
            skipped += 1
            continue
        rows.append(row)

    upsert_many(session, rows)
    _write_cursor(cursor_path, inode, offset)
    return {
        "ingested": len(rows),
        "skipped": skipped,
        "reset": reset,
        "offset": offset,
        "missing": False,
    }


def _tick() -> None:
    from app.db.database import SessionLocal  # noqa: PLC0415 - avoid an import cycle

    session = SessionLocal()
    try:
        ingest_once(
            session,
            log_dir=console_settings.log_dir,
            data_dir=console_settings.data_dir,
        )
    finally:
        session.close()


async def run_forever() -> None:
    """Started and cancelled by `main.lifespan`; no thread, no extra worker.

    The first tick waits one interval on purpose: the pipeline appends its first
    `TURN_LATENCY` line seconds after boot, and a tick inside the startup window
    only competes with the request the operator is making to see the panel at all.
    """
    while True:
        await asyncio.sleep(INTERVAL_S)
        try:
            await asyncio.to_thread(_tick)
        except Exception as exc:  # noqa: BLE001 - one bad tick must not stop the index
            logger.warning("turn latency indexer tick failed: {}", exc)
