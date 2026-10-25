"""`alembic/sql/init-*.sql` is generated, so these tests are the drift guard.

The files come from `scripts/dump_schema_sql.py`, which renders the same
migrations the image upgrades with. If a migration lands without a
regeneration, the file stops covering a model column and this fails — the same
way `alembic check` would fail against a live database.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path

import pytest

import app.models  # noqa: F401 - registers the tables on Base.metadata
from alembic.config import Config
from alembic.script import ScriptDirectory
from app.db.base import Base

BACKEND = Path(__file__).resolve().parents[2]
SQL_DIR = BACKEND / "alembic" / "sql"
DIALECTS = ("sqlite", "postgresql")


def _sql(dialect: str) -> str:
    return (SQL_DIR / f"init-{dialect}.sql").read_text(encoding="utf-8")


def _head() -> str:
    config = Config(str(BACKEND / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND / "alembic"))
    head = ScriptDirectory.from_config(config).get_current_head()
    assert head is not None, "alembic has no head revision"
    return head


def _table_block(sql: str, table: str) -> str:
    start = sql.index(f"CREATE TABLE {table} (")
    return sql[start : sql.index(");", start)]


def test_the_sqlite_file_provisions_a_fresh_database_at_head(tmp_path):
    database = tmp_path / "console.sqlite3"
    with sqlite3.connect(database) as conn:
        conn.executescript(_sql("sqlite"))
        tables = {row[0] for row in conn.execute("select name from sqlite_master where type='table'")}
        stamped = conn.execute("select version_num from alembic_version").fetchone()[0]

    # A database provisioned from the file is already migrated: no `alembic
    # upgrade head` needed afterwards, and no silent schema mismatch either.
    assert stamped == _head()
    assert tables == {table.name for table in Base.metadata.sorted_tables} | {"alembic_version"}


@pytest.mark.parametrize("dialect", DIALECTS)
def test_every_model_column_appears_in_both_dialects(dialect):
    sql = _sql(dialect)
    missing = [
        f"{table.name}.{column.name}"
        for table in Base.metadata.sorted_tables
        for column in table.columns
        if not re.search(rf"^\s+{re.escape(column.name)} ", _table_block(sql, table.name), re.MULTILINE)
    ]
    assert missing == [], f"{dialect} is missing {missing}; re-run scripts/dump_schema_sql.py"


@pytest.mark.parametrize("dialect", DIALECTS)
def test_both_files_walk_the_same_migration_chain(dialect):
    sql = _sql(dialect)
    # One CREATE TABLE per model table plus alembic's own version table, and
    # every revision stamped exactly once — two heads would break the upgrade.
    assert sql.count("CREATE TABLE ") == len(Base.metadata.sorted_tables) + 1
    assert "VALUES ('0001_initial')" in sql
    assert f"version_num='{_head()}'" in sql


def test_the_dialects_use_their_own_types():
    sqlite, postgres = _sql("sqlite"), _sql("postgresql")
    assert "SERIAL" in postgres and "TIMESTAMP WITH TIME ZONE" in postgres
    assert "SERIAL" not in sqlite and "TIMESTAMP" not in sqlite
    assert "DATETIME" in sqlite
    # Both keep the two indexes: the panels read "this window, newest first".
    for sql in (sqlite, postgres):
        assert "CREATE INDEX ix_voices_status ON voices (status);" in sql
        assert "CREATE INDEX ix_turn_latency_logged_at ON turn_latency (logged_at);" in sql
