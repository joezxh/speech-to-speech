"""每日用量、会话预留与搜索配额（`USAGE_DB_PATH`，默认 `/app/data/usage.sqlite3`）。

移植自 `demo/limiter.py`，语义逐条照搬；存储仍是裸 `sqlite3`（D11）：参数库走
SQLAlchemy，用量库不共用连接池——两套 WAL、两套备份、互不阻塞。

每个函数都在请求路径上，所以只有一个模块级锁，没有 ORM，没有异步。
调用方负责把它塞进线程池（路由写成同步 `def` 就够了）。
"""

from __future__ import annotations

import hashlib
import hmac
import math
import os
import sqlite3
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from loguru import logger

from app.config import database

# ── 可调参数：环境变量名与 demo 完全一致，运维不用学第二套名字 ──────────────
ANON_SEC = int(os.environ.get("LIMIT_ANON_SEC", "300"))  # 未登录：5 分钟/天
FREE_SEC = int(os.environ.get("LIMIT_FREE_SEC", "600"))  # 已登录非 PRO：10 分钟/天
CHUNK_SEC = int(os.environ.get("RESERVE_CHUNK_SEC", "10"))  # 预留粒度
HEARTBEAT_SEC = int(os.environ.get("HEARTBEAT_SEC", "5"))  # 下发给客户端的心跳节奏
REAP_AFTER_SEC = int(os.environ.get("SESSION_REAP_SEC", "15"))  # 静默多久算掉线
SEARCH_PER_DAY = int(os.environ.get("LIMIT_SEARCH_PER_DAY", "100"))  # 服务端 key 的搜索上限

UNLIMITED_TIERS = ("pro", "org")

# 跨重启必须稳定，否则哈希键（以及签名 cookie）全部轮换，当日额度等于清零。
# Space 上配 USAGE_HASH_SECRET；没配就每次启动随机——额度只在一个 uptime 内有效。
_HASH_SECRET = (os.environ.get("USAGE_HASH_SECRET", "").strip() or os.urandom(32).hex()).encode()

_lock = threading.Lock()
_db_path: Path | None = None


def budget_for(tier: str) -> int | None:
    """某档位的每日秒数预算；不限量的档位返回 `None`，不是一个大数字。"""
    if tier in UNLIMITED_TIERS:
        return None
    if tier == "free":
        return FREE_SEC
    return ANON_SEC


def hash_key(raw: str) -> str:
    """把裸标识（sub / ip / cookie id）HMAC 成不透明存储键。"""
    digest = hmac.new(_HASH_SECRET, raw.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"k_{digest}"


def sign_cookie(value: str) -> str:
    """`<id>.<sig>`，读回时能识别伪造的匿名 id。"""
    sig = hmac.new(_HASH_SECRET, value.encode("utf-8"), hashlib.sha256).hexdigest()[:32]
    return f"{value}.{sig}"


def verify_cookie(signed: str) -> str | None:
    """签名对得上就回 id，否则 `None`。"""
    if not signed or "." not in signed:
        return None
    value, _, sig = signed.rpartition(".")
    want = hmac.new(_HASH_SECRET, value.encode("utf-8"), hashlib.sha256).hexdigest()[:32]
    return value if hmac.compare_digest(sig, want) else None


def init(path: str | None = None) -> None:
    """建表。lifespan 里调一次（demo 的 `@app.on_event("startup")` 同一位置）。"""
    global _db_path
    target = Path(path or database.usage_db_path)
    # /app/data 是命名卷，首次起来是空目录；sqlite3 不会替你建父目录。
    target.parent.mkdir(parents=True, exist_ok=True)
    _db_path = target
    with _lock, _session() as con:
        con.execute(
            """CREATE TABLE IF NOT EXISTS usage_daily (
                   user_key   TEXT NOT NULL,
                   day        TEXT NOT NULL,
                   spent_sec  INTEGER NOT NULL DEFAULT 0,
                   updated_at INTEGER NOT NULL,
                   PRIMARY KEY (user_key, day)
               )"""
        )
        con.execute(
            """CREATE TABLE IF NOT EXISTS sessions (
                   session_id   TEXT PRIMARY KEY,
                   keys         TEXT NOT NULL,   -- 逗号串：要扣的 usage_daily 键
                   day          TEXT NOT NULL,
                   tier         TEXT NOT NULL,
                   grant_ts     REAL NOT NULL,
                   last_seen_ts REAL NOT NULL,
                   reserved_sec INTEGER NOT NULL,
                   ended        INTEGER NOT NULL DEFAULT 0
               )"""
        )
        con.execute(
            """CREATE TABLE IF NOT EXISTS search_daily (
                   user_key TEXT NOT NULL,
                   day      TEXT NOT NULL,
                   count    INTEGER NOT NULL DEFAULT 0,
                   PRIMARY KEY (user_key, day)
               )"""
        )
    logger.info(
        "usage metering ready at {} (anon={}s free={}s chunk={}s)",
        _db_path, ANON_SEC, FREE_SEC, CHUNK_SEC,
    )


def _connect() -> sqlite3.Connection:
    if _db_path is None:
        # 没有 init 就来扣额度说明 lifespan 没跑：宁可炸，也不要静默地让人白嫖。
        raise RuntimeError("metering_service.init() must run in the lifespan before any request")
    con = sqlite3.connect(_db_path, timeout=5.0)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=5000")
    return con


@contextmanager
def _session() -> Iterator[sqlite3.Connection]:
    """`with con:` 只提交不关闭（demo 靠 GC 兜底）；这里显式关掉，语义不变。"""
    con = _connect()
    try:
        with con:
            yield con
    finally:
        con.close()


def _today() -> str:
    return datetime.now(UTC).date().isoformat()


def _spent(con: sqlite3.Connection, key: str, day: str) -> int:
    row = con.execute(
        "SELECT spent_sec FROM usage_daily WHERE user_key=? AND day=?", (key, day)
    ).fetchone()
    return int(row[0]) if row else 0


def _spent_max(con: sqlite3.Connection, keys, day: str) -> int:
    """OR-match：花得最多的那个标识说了算（换 IP 换不出新额度，见本任务说明）。"""
    return max((_spent(con, k, day) for k in keys), default=0)


def _add(con: sqlite3.Connection, keys, day: str, delta: int) -> None:
    now = int(time.time())
    for k in keys:
        nxt = max(0, _spent(con, k, day) + delta)
        con.execute(
            """INSERT INTO usage_daily (user_key, day, spent_sec, updated_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(user_key, day) DO UPDATE SET
                   spent_sec = excluded.spent_sec, updated_at = excluded.updated_at""",
            (k, day, nxt, now),
        )


def remaining(keys, tier: str) -> int | None:
    """今天还剩多少秒（`None` = 不限量）。只读，不产生写入。"""
    budget = budget_for(tier)
    if budget is None:
        return None
    with _lock, _session() as con:
        return max(0, budget - _spent_max(con, keys, _today()))


def begin(session_id: str, keys, tier: str) -> int:
    """给新会话预留第一块并记账，返回预留秒数（预算已耗尽时为 0）。

    不限量档位也记一行：Web 搜索要靠这一行判断「这个会话是不是活的」。
    """
    day = _today()
    budget = budget_for(tier)
    now = time.time()
    with _lock, _session() as con:
        avail = budget - _spent_max(con, keys, day) if budget is not None else 0
        chunk = max(0, min(CHUNK_SEC, avail))
        if chunk:
            _add(con, keys, day, chunk)
        con.execute(
            """INSERT OR REPLACE INTO sessions
               (session_id, keys, day, tier, grant_ts, last_seen_ts, reserved_sec, ended)
               VALUES (?, ?, ?, ?, ?, ?, ?, 0)""",
            (session_id, ",".join(keys), day, tier, now, now, chunk),
        )
        return chunk


def heartbeat(session_id: str) -> bool:
    """续期：把预留追到 `elapsed + 一块`，逐块扣预算。

    返回 True = 会话还活着；False = 预算花完（调用方必须拆会话）或会话未知/已结束。
    """
    now = time.time()
    with _lock, _session() as con:
        row = con.execute(
            "SELECT keys, day, tier, grant_ts, reserved_sec, ended FROM sessions WHERE session_id=?",
            (session_id,),
        ).fetchone()
        if not row or row[5]:
            return False
        keys = row[0].split(",")
        day, tier, grant_ts, reserved = row[1], row[2], row[3], int(row[4])
        budget = budget_for(tier)
        if budget is None:
            # 不限量：没有账可记，心跳只用来表示「这个会话还在」。
            con.execute("UPDATE sessions SET last_seen_ts=? WHERE session_id=?", (now, session_id))
            return True
        elapsed = now - grant_ts

        # 一块一块往上加，直到覆盖「已用时长 + 一块的提前量」，或者预算见底。
        while reserved < elapsed + CHUNK_SEC:
            if _spent_max(con, keys, day) >= budget:
                break
            _add(con, keys, day, CHUNK_SEC)
            reserved += CHUNK_SEC

        alive = reserved > elapsed  # 已经过去的时间还付得起吗？
        con.execute(
            "UPDATE sessions SET last_seen_ts=?, reserved_sec=?, ended=? WHERE session_id=?",
            (now, reserved, 0 if alive else 1, session_id),
        )
        if not alive:
            _reconcile(con, keys, day, grant_ts, reserved, end_ts=now)
        return alive


def end(session_id: str) -> None:
    """正常结束：按真实时长结算，退回没用掉的预留。幂等。"""
    now = time.time()
    with _lock, _session() as con:
        row = con.execute(
            "SELECT keys, day, grant_ts, reserved_sec, ended FROM sessions WHERE session_id=?",
            (session_id,),
        ).fetchone()
        if not row or row[4]:
            return
        keys, day, grant_ts, reserved = row[0].split(","), row[1], row[2], int(row[3])
        _reconcile(con, keys, day, grant_ts, reserved, end_ts=now)
        con.execute("UPDATE sessions SET ended=1, last_seen_ts=? WHERE session_id=?", (now, session_id))


def sweep() -> None:
    """回收静默掉的计量会话（崩了 / 关页没发 beacon）：按走过的时长结算、
    退回其余、标记结束。最多损失一块。

    不限量会话没有账可结，留着不关：断线后一次心跳就能复活，期间
    `session_live()` 视它们为过期。只有显式 `end()` 才真正关闭。"""
    now = time.time()
    cutoff = now - REAP_AFTER_SEC
    unlimited = ",".join("?" * len(UNLIMITED_TIERS))
    with _lock, _session() as con:
        stale = con.execute(
            "SELECT session_id, keys, day, grant_ts, last_seen_ts, reserved_sec FROM sessions "
            f"WHERE ended=0 AND last_seen_ts < ? AND tier NOT IN ({unlimited})",
            (cutoff, *UNLIMITED_TIERS),
        ).fetchall()
        for session_id, keys_s, day, grant_ts, last_seen, reserved in stale:
            _reconcile(con, keys_s.split(","), day, grant_ts, int(reserved), end_ts=last_seen)
            con.execute("UPDATE sessions SET ended=1 WHERE session_id=?", (session_id,))
        if stale:
            logger.debug("swept {} stale session(s)", len(stale))


def session_live(session_id: str, keys) -> bool:
    """这个 `session_id` 是否是发给这组 keys 的、还没结束、且 `REAP_AFTER_SEC`
    内有过动静（授权或心跳）的会话。"""
    if not session_id:
        return False
    with _lock, _session() as con:
        row = con.execute(
            "SELECT keys, ended, last_seen_ts FROM sessions WHERE session_id=?", (session_id,)
        ).fetchone()
    return (
        bool(row)
        and not row[1]
        and row[0] == ",".join(keys)
        and row[2] >= time.time() - REAP_AFTER_SEC
    )


def take_search(keys) -> bool:
    """给服务端 key 的一次搜索记一笔（OR-match，与时长预算同规则）。
    达到上限时返回 False 且不记账。"""
    day = _today()
    with _lock, _session() as con:
        counts = [
            con.execute(
                "SELECT count FROM search_daily WHERE user_key=? AND day=?", (k, day)
            ).fetchone()
            for k in keys
        ]
        if max((int(c[0]) for c in counts if c), default=0) >= SEARCH_PER_DAY:
            return False
        for k in keys:
            con.execute(
                """INSERT INTO search_daily (user_key, day, count) VALUES (?, ?, 1)
                   ON CONFLICT(user_key, day) DO UPDATE SET count = count + 1""",
                (k, day),
            )
        return True


def _reconcile(con: sqlite3.Connection, keys, day: str, grant_ts: float, reserved: int, end_ts: float) -> None:
    """退回「预留了但没用」的时间。已用时长向上取整到整块，且不超过预留。"""
    elapsed = max(0.0, end_ts - grant_ts)
    billed = min(reserved, int(math.ceil(elapsed / CHUNK_SEC) * CHUNK_SEC))
    refund = reserved - billed
    if refund > 0:
        _add(con, keys, day, -refund)
