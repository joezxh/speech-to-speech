"""A.15: a read-only tail over the four supervisor logs.

The four files are the whole input. `read()` is synchronous so the router can
wrap it in `asyncio.to_thread(..., 1.5s)` and fall back to a partial page: a
console that blocks on a 2 GB log while the pipeline is down helps nobody.

The cursor is not a line number. Rotation rewrites line numbers and keeps the
file name, so the only reliable "this is a different file" signal is the inode
(plus "the file shrank"). It is base64'd because the client must treat it as
opaque — the encoding is the server's business.
"""

from __future__ import annotations

import base64
import json
import re
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SOURCES = ("console-stdout.log", "console-stderr.log", "pipeline-stdout.log", "pipeline-stderr.log")
PROCESSES = ("console", "pipeline")
LEVELS = ("ERROR", "WARN", "INFO")

# One page never reads more than this from the end of a file (§A.15 budget).
TAIL_BYTES = 256 * 1024

_ERROR_LEVEL = re.compile(r'"level"\s*:\s*"(?:error|fatal|critical|traceback)"', re.IGNORECASE)
_TS_JSON = re.compile(r'"(?:time|timestamp)"\s*:\s*"([^"]+)"')
_TS_LEADING = re.compile(r"^\[?(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?(?:Z|[+-]\d{2}:?\d{2})?)")


class LogsUnavailable(Exception):
    """The directory is absent or unreadable — a 503, not a 500 (§A.15)."""


def _encode_cursor(entries: dict[str, tuple[int, int]]) -> str:
    payload = json.dumps({name: [inode, offset] for name, (inode, offset) in entries.items()}, separators=(",", ":"))
    return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii").rstrip("=")


def _decode_cursor(value: str) -> dict[str, tuple[int, int]]:
    if not value:
        return {}
    try:
        padded = value + "=" * (-len(value) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        # A cursor from an older build (or a hand-typed one) is not an error:
        # read the tail again rather than refusing the page.
        return {}
    if not isinstance(payload, dict):
        return {}
    entries: dict[str, tuple[int, int]] = {}
    for name, pair in payload.items():
        if name not in SOURCES or not isinstance(pair, list) or len(pair) != 2:
            continue
        try:
            entries[name] = (int(pair[0]), int(pair[1]))
        except (TypeError, ValueError):
            continue
    return entries


def _parse_ts(value: str) -> datetime | None:
    text = value.strip()
    if not text:
        return None
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    text = text.replace(",", ".")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _iso(value: datetime | None) -> str:
    if value is None:
        return ""
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _window(from_iso: str | None, to_iso: str | None) -> tuple[datetime | None, datetime | None]:
    """No implicit window: A.15's 15-minute default belongs to the endpoint.

    Keeping it out of the reader is what lets a test read a file with a fixed
    timestamp, and what keeps `read()` a pure function of its arguments.
    """
    start = _parse_ts(from_iso) if from_iso else None
    end = _parse_ts(to_iso) if to_iso else None
    if (from_iso and start is None) or (to_iso and end is None):
        raise ValueError("from/to must be ISO 8601 timestamps")
    if start is not None and end is not None and start > end:
        raise ValueError("from must not be after to")
    return start, end


def _line_timestamp(text: str) -> datetime | None:
    match = _TS_JSON.search(text)
    if match is not None:
        parsed = _parse_ts(match.group(1))
        if parsed is not None:
            return parsed
    match = _TS_LEADING.match(text)
    if match is not None:
        return _parse_ts(match.group(1))
    return None


def _level(text: str) -> str:
    if _ERROR_LEVEL.search(text) or "ERROR" in text or "Traceback (most recent call last)" in text:
        return "ERROR"
    if "WARNING" in text or "WARN" in text:
        return "WARN"
    # No `unknown` bucket: a fourth level would vanish whenever the UI filters
    # by level, which is the one time the panel must be complete (§A.15).
    return "INFO"


def _selected(process: Iterable[str] | None) -> list[str]:
    wanted = {name for name in (process or PROCESSES) if name in PROCESSES}
    if not wanted:
        wanted = set(PROCESSES)
    # SOURCES order, not the caller's: `console` before `pipeline` keeps ties
    # between two simultaneous lines stable across calls.
    return [name for name in SOURCES if name.split("-")[0] in wanted]


def _read_from(path: Path, start: int) -> tuple[bytes, int, bool]:
    """Read forward from `start`, returning (complete lines, new offset, cut)."""
    size = path.stat().st_size
    cropped = False
    if start < 0 or start > size:
        start = 0
        cropped = True
    if size - start > TAIL_BYTES:
        start = size - TAIL_BYTES
        cropped = True
    with path.open("rb") as handle:
        handle.seek(start)
        raw = handle.read()
    if start > 0 and raw:
        # The window (or a half-written line) may start mid-line. Drop it: a
        # half line would be reported as a fabricated error signature.
        with path.open("rb") as handle:
            handle.seek(start - 1)
            boundary = handle.read(1)
        if boundary != b"\n":
            cut = raw.find(b"\n")
            if cut == -1:
                return b"", start, cropped
            start += cut + 1
            raw = raw[cut + 1 :]
    if raw and not raw.endswith(b"\n"):
        # Keep the trailing partial line for the next poll, which will see it
        # complete. Advancing past it would drop the rest of that line.
        cut = raw.rfind(b"\n")
        if cut == -1:
            return b"", start, cropped
        raw = raw[: cut + 1]
    return raw, start + len(raw), cropped


def _iter_lines(raw: bytes, start: int) -> Iterable[tuple[int, str]]:
    position = start
    for chunk in raw.split(b"\n"):
        if not chunk:
            position += 1
            continue
        yield position, chunk.decode("utf-8", "replace").rstrip("\r")
        position += len(chunk) + 1


def _sources(root: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for name in SOURCES:
        path = root / name
        try:
            stat = path.stat()
        except OSError:
            entries.append({"file": name, "size": 0, "mtime": None})
            continue
        entries.append(
            {
                "file": name,
                "size": int(stat.st_size),
                "mtime": _iso(datetime.fromtimestamp(stat.st_mtime, UTC)),
            }
        )
    return entries


def read(
    *,
    log_dir: str | Path,
    process: Iterable[str] | None = None,
    level: Iterable[str] | None = None,
    from_iso: str | None = None,
    to_iso: str | None = None,
    q: str = "",
    after: str = "",
    limit: int = 500,
) -> dict[str, Any]:
    root = Path(log_dir)
    if not root.is_dir():
        raise LogsUnavailable(f"log directory is missing: {root}")

    start_at, end_at = _window(from_iso, to_iso)
    wanted_levels = {item.upper() for item in (level or ())}
    needle = q.strip().lower()
    cursor = _decode_cursor(after)

    collected: list[dict[str, Any]] = []
    positions: dict[str, tuple[int, int]] = {}
    reset = False
    budget_cut = False
    files_read = 0
    bytes_read = 0

    for name in _selected(process):
        path = root / name
        if not path.is_file():
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        files_read += 1
        inode = int(getattr(stat, "st_ino", 0))
        start = 0
        previous = cursor.get(name)
        if previous is not None:
            previous_inode, previous_offset = previous
            if previous_inode != inode or int(stat.st_size) < previous_offset:
                reset = True
            else:
                start = previous_offset

        raw, new_offset, cropped = _read_from(path, start)
        bytes_read += len(raw)
        budget_cut = budget_cut or cropped
        positions[name] = (inode, new_offset)

        # Continuation lines (tracebacks, wrapped messages) carry no timestamp;
        # they belong to the last timestamped line in the same file.
        current_ts: str = ""
        current_dt: datetime | None = None
        stream = name.rsplit("-", 1)[-1].removesuffix(".log")
        for offset, text in _iter_lines(raw, start):
            parsed = _line_timestamp(text)
            if parsed is not None:
                current_dt, current_ts = parsed, _iso(parsed)
            if current_dt is not None:
                if (start_at is not None and current_dt < start_at) or (end_at is not None and current_dt > end_at):
                    continue
            if needle and needle not in text.lower():
                continue
            inferred = _level(text)
            if wanted_levels and inferred not in wanted_levels:
                continue
            collected.append(
                {
                    "ts": current_ts,
                    "process": name.split("-")[0],
                    "stream": stream,
                    "level": inferred,
                    "text": text,
                    "file": name,
                    "offset": offset,
                }
            )
        if cropped:
            # At least one file lost its head to the 256 KiB cap in this page.
            budget_cut = True

    collected.sort(key=lambda line: (line["ts"], line["process"], line["file"], line["offset"]))
    truncated = budget_cut or len(collected) > limit
    if len(collected) > limit:
        # Newest wins: a log panel that shows the oldest 500 lines of an
        # incident window answers the wrong question.
        collected = collected[-limit:]

    merged = {**cursor, **positions}
    return {
        "lines": collected,
        "nextCursor": _encode_cursor(merged),
        "reset": reset,
        "truncated": truncated,
        "scanned": {"files": files_read, "bytes": bytes_read},
        "sources": _sources(root),
    }


def partial(*, limit: int = 0) -> dict[str, Any]:
    """The page to return when `wait_for` expired: empty, and honest about it.

    `limit` is echoed only to keep the router's call shape identical to the
    `read()` call it replaces.
    """
    del limit
    return {
        "lines": [],
        "nextCursor": "",
        "reset": False,
        "truncated": True,
        "scanned": {"files": 0, "bytes": 0},
        "sources": [],
    }
