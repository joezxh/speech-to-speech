"""工具仓储与服务：可见性、effectiveEnabled、所有权、CRUD（Task 2 RED）。"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.models.tool import ConsoleTool
from app.schemas.tool import ToolCreate, ToolUpdate
from app.services import tool_service


BUILTINS = [
    ("tool-search", "Web search", "web_search", "global", True),
    ("tool-calendar", "Calendar", "calendar", "global", False),
    ("tool-weather", "Weather", "weather", "global", True),
    ("tool-kb", "Knowledge base", "kb", "tenant", False),
]


def _seed_builtins(db: Session) -> None:
    for tool_id, name, kind, scope, enabled in BUILTINS:
        db.add(
            ConsoleTool(
                id=tool_id,
                name=name,
                type=kind,
                scope=scope,
                enabled=enabled,
                builtin=True,
                owner="",
                params=[],
                config={},
            )
        )
    db.commit()


def test_builtin_tools_visible_to_all(db_session):
    _seed_builtins(db_session)
    rows = tool_service.list_tools(db_session, "bob")
    assert {row["id"] for row in rows} == {tool[0] for tool in BUILTINS}
    by_id = {row["id"]: row for row in rows}
    assert by_id["tool-search"]["effectiveEnabled"] is True
    assert by_id["tool-calendar"]["effectiveEnabled"] is False
    assert by_id["tool-kb"]["scope"] == "tenant"


def test_custom_tool_owner_isolation(db_session):
    _seed_builtins(db_session)
    tool_service.create_tool(
        db_session,
        ToolCreate(name="Private", type="http", scope="tenant", endpoint="https://example.com/hook", params=[]),
        actor="alice",
        username="alice",
        role="operator",
    )
    assert "Private" not in {row["name"] for row in tool_service.list_tools(db_session, "bob")}
    assert "Private" in {row["name"] for row in tool_service.list_tools(db_session, "alice")}


def test_duplicate_name_raises(db_session):
    _seed_builtins(db_session)
    payload = ToolCreate(name="Web search", type="http", scope="global", endpoint="https://example.com/hook", params=[])
    with pytest.raises(ValueError):
        tool_service.create_tool(db_session, payload, actor="alice", username="alice", role="admin")


def test_toggle_changes_effective_enabled(db_session):
    _seed_builtins(db_session)
    tool_service.toggle_tool(db_session, "tool-calendar", True, actor="op", username="op")
    rows = {row["id"]: row for row in tool_service.list_tools(db_session, "op")}
    assert rows["tool-calendar"]["effectiveEnabled"] is True


def test_session_scope_effective_enabled_is_none(db_session):
    _seed_builtins(db_session)
    tool_service.create_tool(
        db_session,
        ToolCreate(name="Session only", type="http", scope="session", endpoint="https://example.com/hook", params=[]),
        actor="alice",
        username="alice",
        role="operator",
    )
    row = next(r for r in tool_service.list_tools(db_session, "alice") if r["name"] == "Session only")
    assert row["effectiveEnabled"] is None


def test_copy_creates_new_id(db_session):
    _seed_builtins(db_session)
    copied = tool_service.copy_tool(db_session, "tool-weather", actor="alice", username="alice", role="operator")
    assert copied["id"] != "tool-weather"
    assert copied["name"] == "Weather Copy"
    assert copied["builtin"] is False


def test_copy_twice_gets_unique_names(db_session):
    _seed_builtins(db_session)
    first = tool_service.copy_tool(db_session, "tool-weather", actor="alice", username="alice", role="operator")
    second = tool_service.copy_tool(db_session, "tool-weather", actor="alice", username="alice", role="operator")
    assert first["name"] == "Weather Copy"
    assert second["name"] == "Weather Copy 2"


def test_toggle_session_tool_does_not_persist(db_session):
    _seed_builtins(db_session)
    created = tool_service.create_tool(
        db_session,
        ToolCreate(name="Session", type="http", scope="session", endpoint="https://example.com", params=[]),
        actor="alice", username="alice", role="operator",
    )
    out = tool_service.toggle_tool(db_session, created["id"], False, actor="alice", username="alice")
    assert out["effectiveEnabled"] is None
    row = next(r for r in tool_service.list_tools(db_session, "alice") if r["id"] == created["id"])
    assert row["enabled"] is created["enabled"]


def test_update_tool_changes_description(db_session):
    _seed_builtins(db_session)
    updated = tool_service.update_tool(
        db_session, "tool-weather", ToolUpdate(description="新描述"), actor="alice", username="alice", role="operator"
    )
    assert updated["description"] == "新描述"
