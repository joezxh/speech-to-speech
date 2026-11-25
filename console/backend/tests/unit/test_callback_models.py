"""callback_target / callback_delivery_log 模型与迁移测试（sqlite 内存库）。"""
from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from app.db.base import Base
from app.models.callbacks import CallbackDeliveryLog, CallbackTarget

BACKEND = Path(__file__).resolve().parents[2]


@pytest.fixture()
def session() -> Session:
    engine = create_engine("sqlite://")
    # SQLite 默认不启用外键，SET NULL 软关联只有开了 PRAGMA 才与 PostgreSQL 同语义。
    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, connection_record):  # noqa: ANN001
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


def test_target_roundtrip(session: Session) -> None:
    target = CallbackTarget(
        name="ai-server", target_type="java", base_url="http://ai-server",
        auth_type="header_token", auth_header_name="X-Internal-Token", auth_token="secret",
        extra_headers={"tenant-id": "1"}, timeout_ms=3000, retry_max_attempts=3,
        retry_backoff_ms=500, events=["transcript"], filters=None, enabled=True,
    )
    session.add(target)
    session.flush()
    row = session.query(CallbackTarget).one()
    assert row.target_type == "java"
    assert row.extra_headers == {"tenant-id": "1"}
    assert row.events == ["transcript"]
    assert row.timeout_ms == 3000


def test_log_set_null_on_target_delete(session: Session) -> None:
    target = CallbackTarget(name="webhook", target_type="python", base_url="http://x",
                            auth_type="none", auth_token="", extra_headers={},
                            timeout_ms=3000, retry_max_attempts=1, retry_backoff_ms=0,
                            events=["transcript"], enabled=True)
    session.add(target)
    session.flush()
    log = CallbackDeliveryLog(target_id=target.id, event_type="transcript",
                              triggered_at=target.created_at, request_url="http://x",
                              request_payload="{}", attempt=1, http_status=200,
                              response_snippet="ok", duration_ms=10, status="success", error="")
    session.add(log)
    session.commit()
    session.delete(target)
    session.commit()
    row = session.query(CallbackDeliveryLog).one()
    assert row.target_id is None  # SET NULL：日志保留


def test_migration_up_and_down(tmp_path) -> None:
    """alembic upgrade head + downgrade -1 + upgrade head 可执行（0015 可逆）。

    env.py 从 app.config.database 读 URL（DATABASE_URL 环境变量），且 settings 在
    import 期固化 —— 与 test_lb_backbone_models / dump_schema_sql 一致地用子进程。
    """
    database = tmp_path / "mig.db"
    env = {
        **os.environ,
        "DATABASE_URL": f"sqlite:///{database.as_posix()}",
        "JWT_SECRET_KEY": "migration-test-placeholder-at-least-32-bytes",
        "PYTHONPATH": str(BACKEND),
    }

    def alembic(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "alembic", *args],
            cwd=BACKEND,
            env=env,
            capture_output=True,
            text=True,
        )

    def tables() -> set[str]:
        with sqlite3.connect(database) as conn:
            return {row[0] for row in conn.execute("select name from sqlite_master where type='table'")}

    upgraded = alembic("upgrade", "head")
    assert upgraded.returncode == 0, upgraded.stderr
    assert {"callback_target", "callback_delivery_log"} <= tables()

    downgraded = alembic("downgrade", "-1")
    assert downgraded.returncode == 0, downgraded.stderr
    assert not ({"callback_target", "callback_delivery_log"} & tables())

    again = alembic("upgrade", "head")
    assert again.returncode == 0, again.stderr
    assert {"callback_target", "callback_delivery_log"} <= tables()
