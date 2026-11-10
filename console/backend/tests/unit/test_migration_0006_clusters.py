"""0006_clusters 迁移的形状与 seed（spec §2）。

tests/conftest.py 的 db_session 走 `Base.metadata.create_all`，不跑迁移，
所以这里用 alembic programmatic API 在一个独立临时 SQLite 库上升级到 head，
验证真迁移能跑通且 default 行可重入。
"""
from __future__ import annotations

import importlib.util
import pathlib

import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from alembic.runtime import migration
from alembic.script import ScriptDirectory

from app.config import database

BACKEND_ROOT = pathlib.Path(__file__).resolve().parents[2]


def _config(url: str) -> Config:
    cfg = Config(str(BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
    return cfg


def _upgrade(monkeypatch, url: str, revision: str = "head") -> None:
    # alembic/env.py 在每次加载时用 app.config.database.database_url 强制覆盖
    # ini 的 sqlalchemy.url，所以只能 monkeypatch 这个运行时属性把迁移引到临时库，
    # 否则会真的迁移到 .env 指向的开发库上。
    monkeypatch.setattr(database, "database_url", url)
    cfg = _config(url)
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


def _table_names(url: str) -> set[str]:
    engine = sa.create_engine(url)
    try:
        return set(sa.inspect(engine).get_table_names())
    finally:
        engine.dispose()


def _cluster_names(url: str) -> list[str]:
    engine = sa.create_engine(url)
    try:
        with engine.connect() as conn:
            return [r[0] for r in conn.execute(sa.text("SELECT name FROM param_cluster ORDER BY id"))]
    finally:
        engine.dispose()


def _seed_sql():
    # 直接从迁移文件加载同一条 SEED_SQL 常量验证幂等，不在测试里复制 SQL（防漂移）。
    module_path = BACKEND_ROOT / "alembic" / "versions" / "0006_clusters.py"
    spec = importlib.util.spec_from_file_location("m0006_clusters", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.SEED_SQL


def test_upgrade_creates_cluster_table_with_default_seed(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'mig.db'}"
    _upgrade(monkeypatch, url)
    assert "param_cluster" in _table_names(url)
    assert _cluster_names(url) == ["default"]


def test_seed_is_reentrant_when_default_row_exists_first(tmp_path, monkeypatch):
    # spec §2.3 可重入：库里已有 default 行（seed 过或手工补插）时，迁移的
    # seed 语句重跑必须不中断（唯一约束）、不重复插。重跑的是迁移模块自己的
    # SEED_SQL，而不是重跑整个 0006（create_table 不承诺存在即跳过）。
    url = f"sqlite:///{tmp_path / 'mig.db'}"
    _upgrade(monkeypatch, url, "head")
    assert _cluster_names(url) == ["default"]
    engine = sa.create_engine(url)
    try:
        with engine.begin() as conn:
            conn.execute(_seed_sql())  # 第二次执行：已有 default 行
            conn.execute(_seed_sql())  # 第三次执行：仍幂等
    finally:
        engine.dispose()
    assert _cluster_names(url) == ["default"]


def test_instance_cluster_id_backfills_and_index_exists(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path / 'mig.db'}"
    _upgrade(monkeypatch, url, "0005_instances")
    engine = sa.create_engine(url)
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "INSERT INTO param_instance (instance_id, base_url, weight, labels_json, enabled, "
                "drain_requested, created_at, updated_at, updated_by) "
                "VALUES ('legacy-a', 'http://a:8765', 1, '{}', 1, 0, datetime('now'), datetime('now'), 'seed')"
            )
        )
    engine.dispose()
    _upgrade(monkeypatch, url, "head")
    engine = sa.create_engine(url)
    try:
        with engine.connect() as conn:
            value = conn.execute(
                sa.text("SELECT cluster_id FROM param_instance WHERE instance_id = 'legacy-a'")
            ).scalar_one()
        idx = {i["name"] for i in sa.inspect(engine).get_indexes("param_instance")}
    finally:
        engine.dispose()
    assert value == "default"
    assert "ix_param_instance_cluster_id" in idx
