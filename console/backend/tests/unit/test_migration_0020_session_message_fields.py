"""0020_session_message_fields 迁移：消息表加 status/duration_ms 两列。

tests/conftest.py 的 db_session 走 `Base.metadata.create_all`，不跑迁移，
所以这里用 alembic programmatic API 在独立临时 SQLite 库上验证真迁移
（写法沿用 test_migration_0006_clusters.py）。
"""
from __future__ import annotations

import pathlib

import sqlalchemy as sa
from alembic.config import Config
from alembic.runtime import migration
from alembic.script import ScriptDirectory

from alembic import command
from app.config import database

BACKEND_ROOT = pathlib.Path(__file__).resolve().parents[2]


def _config() -> Config:
    cfg = Config(str(BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    return cfg


def _upgrade(monkeypatch, url: str, revision: str = "head") -> None:
    # alembic/env.py 每次加载用 app.config.database.database_url 覆盖 ini 的
    # sqlalchemy.url，只能 monkeypatch 这个运行时属性把迁移引到临时库。
    monkeypatch.setattr(database, "database_url", url)
    cfg = _config()
    heads = set(ScriptDirectory.from_config(cfg).get_heads())
    engine = sa.create_engine(url)
    try:
        with engine.begin() as connection:
            context = migration.MigrationContext.configure(connection)
            already = set(context.get_current_heads()) >= heads
        if not already:
            command.upgrade(cfg, revision)
    finally:
        engine.dispose()


def _columns(url: str) -> dict[str, dict]:
    engine = sa.create_engine(url)
    try:
        return {c["name"]: c for c in sa.inspect(engine).get_columns("param_session_message")}
    finally:
        engine.dispose()


def _default_of(col: dict) -> str:
    raw = col.get("default")
    return "" if raw is None else str(raw).strip("'\"")


def test_upgrade_adds_status_and_duration_ms_with_defaults(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'mig.db'}"
    _upgrade(monkeypatch, url)
    cols = _columns(url)
    assert "status" in cols and "duration_ms" in cols
    assert cols["status"]["nullable"] is False
    assert _default_of(cols["status"]) == "ok"
    assert cols["duration_ms"]["nullable"] is False
    assert _default_of(cols["duration_ms"]) == "0"


def test_downgrade_drops_status_and_duration_ms(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'mig.db'}"
    _upgrade(monkeypatch, url)
    monkeypatch.setattr(database, "database_url", url)
    command.downgrade(_config(), "0019_session_records")
    cols = _columns(url)
    assert "status" not in cols and "duration_ms" not in cols
