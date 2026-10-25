"""SQLite persistence for configuration versions.

Three concerns, one file, all keyed by profile: the single mutable draft, the
append-only version history, and the audit log.

Secrets are absent by design. A `{env: NAME}` reference lives in the YAML, its
value lives in `config/<profile>.env`, and that file is copied to
`<profile>.env.bak.<version>` on publish. Duplicating the value into this
database would give it a second lifetime and a second access path for no gain;
the backup already makes rollback exact.

Versions are append-only. A rollback writes a *new* version whose content equals
the old one and whose `rolled_back_to` names it, so no state that was ever live
can disappear from the history.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger("s2s.params")

# The state machine from spec §4.3. `draft` is not a version state — drafts live
# in their own table and never reach the history.
STATES = ("validated", "publishing", "live", "rolled_back", "failed", "aborted")
# Only these may be the target of a rollback.
ROLLBACKABLE = ("live", "rolled_back")

# Reentrant: `_connect` initialises the store itself when nothing has, and the
# callers already hold this lock.
_lock = threading.RLock()
_db_path: Path | None = None


def resolve_db_path() -> Path:
    explicit = os.environ.get("PARAM_DB_PATH", "").strip()
    if explicit:
        return Path(explicit)
    data = Path("/data")
    if data.is_dir() and os.access(data, os.W_OK):
        return data / "s2s-params.sqlite3"
    # Beside demo/ in the repo layout, so a local run keeps its history.
    return Path(__file__).resolve().parent.parent / "s2s-params.sqlite3"


def init(path: Path | None = None) -> Path:
    """Create the schema. Safe to call more than once."""
    global _db_path
    with _lock:
        if _db_path is None:
            _db_path = path or resolve_db_path()
        with _connect() as con:
            con.executescript(_SCHEMA)
            _migrate(con)
    logger.info("Parameter store ready at %s", _db_path)
    return _db_path


def _migrate(con: sqlite3.Connection) -> None:
    """Add columns a database created by an older build is missing.

    `CREATE TABLE IF NOT EXISTS` does nothing to an existing table, so a store
    that predates `rendered` (the exact text a version served) would fail every
    insert. A demo database is cheap to recreate, but losing the version history
    of a live deployment to a schema change is not.
    """
    columns = {row["name"] for row in con.execute("PRAGMA table_info(versions)")}
    if "rendered" not in columns:
        con.execute("ALTER TABLE versions ADD COLUMN rendered TEXT NOT NULL DEFAULT ''")
        logger.info("Added versions.rendered to an existing parameter store")


def _connect() -> sqlite3.Connection:
    if _db_path is None:
        # Every caller is a handler, and a handler that 500s because startup did
        # not run is a worse outcome than a first request that is 200 ms slower.
        init()
    con = sqlite3.connect(_db_path, timeout=5.0)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=5000")
    # Rollback safety matters more than insert speed: a half-written version
    # would be worse than a slow one.
    con.execute("PRAGMA synchronous=FULL")
    return con


_SCHEMA = """
CREATE TABLE IF NOT EXISTS drafts (
    profile      TEXT PRIMARY KEY,
    payload      TEXT NOT NULL,
    base_version INTEGER NOT NULL,
    updated_at   REAL NOT NULL,
    updated_by   TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS versions (
    version        INTEGER PRIMARY KEY AUTOINCREMENT,
    profile        TEXT NOT NULL,
    status         TEXT NOT NULL,
    payload        TEXT NOT NULL,
    -- The exact YAML text this version served. A rollback restores these bytes
    -- instead of re-applying the patches, which would land on top of whatever a
    -- later publish changed and produce a config that never existed.
    rendered       TEXT NOT NULL DEFAULT '',
    note           TEXT NOT NULL DEFAULT '',
    actor          TEXT NOT NULL DEFAULT '',
    base_version   INTEGER,
    rolled_back_to INTEGER,
    error          TEXT,
    created_at     REAL NOT NULL,
    updated_at     REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS versions_by_profile ON versions (profile, version DESC);

CREATE TABLE IF NOT EXISTS audit (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    profile     TEXT NOT NULL DEFAULT '',
    action      TEXT NOT NULL,
    actor       TEXT NOT NULL DEFAULT '',
    version     INTEGER,
    result      TEXT NOT NULL DEFAULT '',
    detail      TEXT NOT NULL DEFAULT '{}',
    duration_ms INTEGER NOT NULL DEFAULT 0,
    created_at  REAL NOT NULL
);

CREATE INDEX IF NOT EXISTS audit_by_profile ON audit (profile, id DESC);
"""


# ── draft ────────────────────────────────────────────────────────────────────


def get_draft(profile: str) -> dict[str, Any] | None:
    with _lock, _connect() as con:
        row = con.execute("SELECT * FROM drafts WHERE profile=?", (profile,)).fetchone()
    if row is None:
        return None
    return {
        "profile": row["profile"],
        "values": json.loads(row["payload"]),
        "base_version": row["base_version"],
        "updated_at": row["updated_at"],
        "updated_by": row["updated_by"],
    }


def put_draft(
    profile: str, values: dict[str, Any], base_version: int, actor: str = ""
) -> dict[str, Any]:
    """Replace the draft. The caller has already checked `base_version`."""
    now = time.time()
    payload = json.dumps(values, sort_keys=True, ensure_ascii=False)
    with _lock, _connect() as con:
        con.execute(
            """INSERT INTO drafts (profile, payload, base_version, updated_at, updated_by)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(profile) DO UPDATE SET
                   payload=excluded.payload,
                   base_version=excluded.base_version,
                   updated_at=excluded.updated_at,
                   updated_by=excluded.updated_by""",
            (profile, payload, base_version, now, actor),
        )
    return get_draft(profile) or {}


def drop_draft(profile: str) -> None:
    with _lock, _connect() as con:
        con.execute("DELETE FROM drafts WHERE profile=?", (profile,))


# ── versions ─────────────────────────────────────────────────────────────────


def create_version(
    profile: str,
    values: dict[str, Any],
    *,
    rendered: str = "",
    status: str = "validated",
    note: str = "",
    actor: str = "",
    base_version: int | None = None,
    rolled_back_to: int | None = None,
) -> int:
    if status not in STATES:
        raise ValueError(f"unknown version state {status!r}")
    now = time.time()
    payload = json.dumps(values, sort_keys=True, ensure_ascii=False)
    with _lock, _connect() as con:
        cursor = con.execute(
            """INSERT INTO versions
                   (profile, status, payload, rendered, note, actor, base_version,
                    rolled_back_to, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                profile,
                status,
                payload,
                rendered,
                note,
                actor,
                base_version,
                rolled_back_to,
                now,
                now,
            ),
        )
        return int(cursor.lastrowid)


def set_status(version: int, status: str, error: str | None = None) -> None:
    if status not in STATES:
        raise ValueError(f"unknown version state {status!r}")
    with _lock, _connect() as con:
        con.execute(
            "UPDATE versions SET status=?, error=?, updated_at=? WHERE version=?",
            (status, error, time.time(), version),
        )


def get_version(version: int) -> dict[str, Any] | None:
    with _lock, _connect() as con:
        row = con.execute("SELECT * FROM versions WHERE version=?", (version,)).fetchone()
    return _row_to_version(row) if row else None


def latest_live(profile: str, *, exclude: int | None = None) -> dict[str, Any] | None:
    """The most recent version that is (or was) live.

    `rolled_back` counts: a version that ran and was later reverted is still a
    valid rollback target, which is how "undo the undo" works.
    """
    sql = "SELECT * FROM versions WHERE profile=? AND status IN ('live','rolled_back')"
    params: list[Any] = [profile]
    if exclude is not None:
        sql += " AND version<>?"
        params.append(exclude)
    sql += " ORDER BY version DESC LIMIT 1"
    with _lock, _connect() as con:
        row = con.execute(sql, params).fetchone()
    return _row_to_version(row) if row else None


def list_versions(profile: str, limit: int = 50) -> list[dict[str, Any]]:
    with _lock, _connect() as con:
        rows = con.execute(
            "SELECT * FROM versions WHERE profile=? ORDER BY version DESC LIMIT ?",
            (profile, limit),
        ).fetchall()
    return [_row_to_version(row) for row in rows]


def _row_to_version(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "version": row["version"],
        "profile": row["profile"],
        "status": row["status"],
        "values": json.loads(row["payload"]),
        "rendered": row["rendered"],
        "note": row["note"],
        "actor": row["actor"],
        "base_version": row["base_version"],
        "rolled_back_to": row["rolled_back_to"],
        "error": row["error"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


# ── audit ────────────────────────────────────────────────────────────────────


def record_audit(
    action: str,
    *,
    profile: str = "",
    actor: str = "",
    version: int | None = None,
    result: str = "",
    detail: dict[str, Any] | None = None,
    duration_ms: int = 0,
) -> int:
    with _lock, _connect() as con:
        cursor = con.execute(
            """INSERT INTO audit
                   (profile, action, actor, version, result, detail, duration_ms, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                profile,
                action,
                actor,
                version,
                result,
                json.dumps(detail or {}, sort_keys=True, ensure_ascii=False),
                duration_ms,
                time.time(),
            ),
        )
        return int(cursor.lastrowid)


def list_audit(profile: str = "", limit: int = 50) -> list[dict[str, Any]]:
    sql = "SELECT * FROM audit"
    params: list[Any] = []
    if profile:
        sql += " WHERE profile=?"
        params.append(profile)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    with _lock, _connect() as con:
        rows = con.execute(sql, params).fetchall()
    return [
        {
            "id": row["id"],
            "profile": row["profile"],
            "action": row["action"],
            "actor": row["actor"],
            "version": row["version"],
            "result": row["result"],
            "detail": json.loads(row["detail"]),
            "duration_ms": row["duration_ms"],
            "created_at": row["created_at"],
        }
        for row in rows
    ]
