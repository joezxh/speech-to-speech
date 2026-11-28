"""Task 2（2026-11-17 原型对齐计划）——0010_console_lb_backbone 的地基守卫。

断言口径来自计划 Task 2 Step 1：表齐、默认值齐、唯一约束齐、扩列可空、
迁移在 SQLite 上可 upgrade → downgrade 往返（可逆性）。
"""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import app.models  # noqa: F401 - 在 Base.metadata 上注册全部表
from alembic.config import Config
from alembic.script import ScriptDirectory
from app.db.base import Base
from app.models.lb import ParamLbAffinity, ParamLbRouteLog
from app.models.machine import ParamMachine
from app.models.release import ParamRelease
from sqlalchemy import UniqueConstraint

BACKEND = Path(__file__).resolve().parents[2]

NEW_TABLES = {
    "param_machine",
    "param_machine_workload",
    "param_machine_config",
    "param_machine_draft",
    "param_agent_config_version",
    "param_token_metric",
    "param_lb_rule",
    "param_lb_affinity",
    "param_lb_route_log",
    "param_release",
}


def _head() -> str:
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "alembic"))
    head = ScriptDirectory.from_config(config).get_current_head()
    assert head is not None
    return head


def _unique_columns(table) -> set[tuple[str, ...]]:
    return {
        tuple(column.name for column in constraint.columns)
        for constraint in table.constraints
        if isinstance(constraint, UniqueConstraint)
    }


def test_ten_backbone_tables_are_registered():
    assert NEW_TABLES <= {table.name for table in Base.metadata.sorted_tables}


def test_head_is_0022():
    # head 由 0021 前进到 0022（工具注册表 + 本地日历事件）。
    assert _head().startswith("0022")


def test_param_machine_state_defaults_to_pending_register():
    column = ParamMachine.__table__.c.state
    assert column.default is not None
    assert column.default.arg == "pending_register"


def test_param_machine_uniqueness():
    uniques = _unique_columns(ParamMachine.__table__)
    assert ("machine_id",) in uniques
    assert ("token_hash",) in uniques
    assert ("register_code_hash",) in uniques


def test_param_lb_affinity_key_is_the_primary_key():
    assert set(ParamLbAffinity.__table__.primary_key.columns.keys()) == {"affinity_key"}


def test_param_lb_route_log_at_defaults_to_now():
    column = ParamLbRouteLog.__table__.c.at
    assert column.default is not None and callable(column.default.arg)


def test_param_release_profile_version_is_nullable():
    assert ParamRelease.__table__.c.profile_version.nullable


def test_turn_latency_widened_columns_are_nullable():
    table = Base.metadata.tables["turn_latency"]
    for name in ("machine_id", "instance_id", "audio_duration_s"):
        assert table.c[name].nullable, name


def test_param_instance_machine_id_is_nullable():
    assert Base.metadata.tables["param_instance"].c.machine_id.nullable


def test_param_cluster_baseline_profile_defaults_to_prod():
    column = Base.metadata.tables["param_cluster"].c.baseline_profile
    assert not column.nullable
    python_default = column.default is not None and column.default.arg == "prod"
    server_default = column.server_default is not None and "prod" in str(column.server_default.arg)
    assert python_default or server_default


def test_param_agent_config_version_keeps_a_ring_per_machine():
    # Task 6 要求 ack 快照“按机保留最近 N 版”，所以主键是 (machine_id, config_version)，
    # 不能只用 machine_id 做主键（那会只剩一个版本位）。
    table = Base.metadata.tables["param_agent_config_version"]
    assert set(table.primary_key.columns.keys()) == {"machine_id", "config_version"}


def test_0010_upgrade_and_downgrade_roundtrip_on_sqlite(tmp_path):
    database = tmp_path / "mig.db"
    env = {
        **os.environ,
        "DATABASE_URL": f"sqlite:///{database.as_posix()}",
        "JWT_SECRET_KEY": "schema-dump-placeholder-at-least-32-bytes",
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
    assert NEW_TABLES <= tables()

    downgraded = alembic("downgrade", "0009_db_registry_and_config")
    assert downgraded.returncode == 0, downgraded.stderr
    assert not (NEW_TABLES & tables())

    again = alembic("upgrade", "head")
    assert again.returncode == 0, again.stderr
    assert NEW_TABLES <= tables()
