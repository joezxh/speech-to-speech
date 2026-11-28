"""0022_tools 迁移建表与内置工具 seed（Task 1 RED）。"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory


def _config(db_path) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", "alembic")
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db_path}")
    cfg.attributes["connection"] = None
    return cfg


def test_0022_tools_creates_tables_and_seeds_builtins(tmp_path, monkeypatch):
    db_path = tmp_path / "migrate.db"
    monkeypatch.setattr("app.config.database.database_url", f"sqlite:///{db_path}")

    script = ScriptDirectory.from_config(_config(tmp_path / "unused.db"))
    assert script.get_revision("0022_tools").down_revision == "0021_session_clips"

    cfg = _config(db_path)
    command.upgrade(cfg, "0022_tools")

    engine = sa.create_engine(f"sqlite:///{db_path}")
    with engine.connect() as conn:
        names = set(sa.inspect(conn).get_table_names())
        assert {"ai_console_tool", "ai_console_calendar_event"} <= names

        rows = {
            row["id"]: row
            for row in conn.execute(sa.text("SELECT * FROM ai_console_tool")).mappings()
        }
        assert {"tool-search", "tool-calendar", "tool-weather", "tool-kb"} <= set(rows)
        assert rows["tool-search"]["enabled"] == 1
        assert rows["tool-calendar"]["enabled"] == 0
        assert rows["tool-search"]["builtin"] == 1
        assert rows["tool-kb"]["scope"] == "tenant"
        assert rows["tool-kb"]["owner"] == ""
        assert rows["tool-kb"]["endpoint"] == "https://api.example.com/kb/search"
    engine.dispose()

    command.downgrade(cfg, "0021_session_clips")
    engine = sa.create_engine(f"sqlite:///{db_path}")
    with engine.connect() as conn:
        names = set(sa.inspect(conn).get_table_names())
        assert "ai_console_tool" not in names
        assert "ai_console_calendar_event" not in names
    engine.dispose()
