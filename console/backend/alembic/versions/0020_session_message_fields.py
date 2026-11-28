"""会话消息表加 status/duration_ms 两列（历史页消息级 STT/TTS 状态与时长）。

Revision ID: 0020_session_message_fields
Revises: 0019_session_records

`param_session_message` 补消息级质量字段：status（用户行=STT 结果、助手行=TTS
结果，枚举 ok|fail）与 duration_ms（该条语音时长，毫秒）。带 server_default
保证 0019 存量行可用（历史消息按 ok/0 处理）。
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

from app.models.comments import comment_statements

revision = "0020_session_message_fields"
down_revision = "0019_session_records"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "param_session_message",
        sa.Column("status", sa.String(16), server_default="ok", nullable=False),
    )
    op.add_column(
        "param_session_message",
        sa.Column("duration_ms", sa.Integer(), server_default="0", nullable=False),
    )
    # 新列晚于 0014 注释回填建成：对该表补挂中文注释（PG；SQLite 无 COMMENT ON 跳过）。
    for statement in comment_statements(op.get_context().dialect.name):
        if '"param_session_message"' in statement:
            op.execute(sa.text(statement))


def downgrade() -> None:
    op.drop_column("param_session_message", "duration_ms")
    op.drop_column("param_session_message", "status")
