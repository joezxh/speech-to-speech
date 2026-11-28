"""控制台工具注册表 + 本地日历事件（原型 console-refactor-demo.html#/tools）。

Revision ID: 0022_tools
Revises: 0021_session_clips

`ai_console_tool` 一行一个工具：id 稳定（对话页/语音工具声明按 id 引用）；
`builtin=true` 的 4 行在迁移里 seed，对应原型 TOOLS 常量。`params` 存
`[{k,t,req}]`，`config` 存 provider 优先级等执行期配置。`ai_console_calendar_event`
是日历工具在无真实账号授权时的本地事件库，按 owner 隔离。
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0022_tools"
down_revision = "0021_session_clips"
branch_labels = None
depends_on = None

BUILTIN_TOOLS = [
    {
        "id": "tool-search",
        "name": "Web search",
        "type": "web_search",
        "description": "Attach realtime results to the answer.",
        "endpoint": "https://api.example.com/search",
        "method": "GET",
        "scope": "global",
        "enabled": 1,
        "builtin": 1,
        "owner": "",
        "params": [{"k": "query", "t": "string", "req": 1}, {"k": "top_k", "t": "number", "req": 0}],
        "config": {},
    },
    {
        "id": "tool-calendar",
        "name": "Calendar",
        "type": "calendar",
        "description": "Read the schedule and draft events.",
        "endpoint": "https://api.example.com/calendar",
        "method": "GET",
        "scope": "global",
        "enabled": 0,
        "builtin": 1,
        "owner": "",
        "params": [{"k": "range", "t": "string", "req": 0}],
        "config": {},
    },
    {
        "id": "tool-weather",
        "name": "Weather",
        "type": "weather",
        "description": "Current conditions and forecast.",
        "endpoint": "https://api.example.com/weather",
        "method": "GET",
        "scope": "global",
        "enabled": 1,
        "builtin": 1,
        "owner": "",
        "params": [{"k": "city", "t": "string", "req": 1}],
        "config": {},
    },
    {
        "id": "tool-kb",
        "name": "Knowledge base",
        "type": "kb",
        "description": "RAG over internal documents.",
        "endpoint": "https://api.example.com/kb/search",
        "method": "POST",
        "scope": "tenant",
        "enabled": 0,
        "builtin": 1,
        "owner": "",
        "params": [{"k": "query", "t": "string", "req": 1}, {"k": "top_k", "t": "number", "req": 0}],
        "config": {},
    },
]


def upgrade() -> None:
    op.create_table(
        "ai_console_tool",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("type", sa.String(32), nullable=False),
        sa.Column("description", sa.String(512), nullable=False, server_default=""),
        sa.Column("endpoint", sa.String(512), nullable=False, server_default=""),
        sa.Column("method", sa.String(8), nullable=False, server_default="GET"),
        sa.Column("scope", sa.String(16), nullable=False, server_default="global"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("builtin", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("owner", sa.String(64), nullable=False, server_default=""),
        sa.Column("params", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("config", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("created_by", sa.String(64), nullable=False, server_default=""),
        sa.Column("updated_by", sa.String(64), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("name", name="uq_ai_console_tool_name"),
    )
    op.create_index("ix_ai_console_tool_type", "ai_console_tool", ["type"])
    op.create_index("ix_ai_console_tool_owner", "ai_console_tool", ["owner"])

    op.create_table(
        "ai_console_calendar_event",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("owner", sa.String(64), nullable=False, server_default=""),
        sa.Column("title", sa.String(256), nullable=False),
        sa.Column("start_at", sa.String(32), nullable=False, server_default=""),
        sa.Column("end_at", sa.String(32), nullable=False, server_default=""),
        sa.Column("description", sa.String(1024), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_ai_console_calendar_event_owner", "ai_console_calendar_event", ["owner"])

    import json
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()
    columns = (
        "id,name,type,description,endpoint,method,scope,enabled,builtin,owner,params,config,"
        "created_by,updated_by,created_at,updated_at"
    )
    for row in BUILTIN_TOOLS:
        def literal(value) -> str:
            if isinstance(value, (dict, list)):
                value = json.dumps(value, ensure_ascii=False)
            return "'" + str(value).replace("'", "''") + "'"

        values = ", ".join(
            [
                literal(row["id"]), literal(row["name"]), literal(row["type"]),
                literal(row["description"]), literal(row["endpoint"]), literal(row["method"]),
                literal(row["scope"]), "1" if row["enabled"] else "0", "1" if row["builtin"] else "0",
                literal(row["owner"]), literal(row["params"]), literal(row["config"]),
                "'system'", "'system'", literal(now), literal(now),
            ]
        )
        op.execute(f"INSERT INTO ai_console_tool ({columns}) VALUES ({values})")


def downgrade() -> None:
    op.drop_index("ix_ai_console_calendar_event_owner", table_name="ai_console_calendar_event")
    op.drop_table("ai_console_calendar_event")
    op.drop_index("ix_ai_console_tool_owner", table_name="ai_console_tool")
    op.drop_index("ix_ai_console_tool_type", table_name="ai_console_tool")
    op.drop_table("ai_console_tool")
