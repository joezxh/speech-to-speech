"""会话记录表 + 会话消息表（对话页/历史页的会话记录管理落库）。

Revision ID: 0019_session_records
Revises: 0018_templates

`param_session_record`：一次语音通话 = 一条记录（前端 stop() 时保存逐行转写
摘要：轮数、时长、TTFA、实例/节点）。`param_session_message`：会话内的消息
行（用户/助手/工具），ordinal 保持通话顺序；编辑/单删/清空均只动消息行。
消息随会话删除级联清理（ON DELETE CASCADE）。
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0019_session_records"
down_revision = "0018_templates"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "param_session_record",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("title", sa.String(200), server_default="", nullable=False),
        sa.Column("note", sa.String(500), server_default="", nullable=False),
        sa.Column("pipeline_session_id", sa.String(128), server_default="", nullable=False),
        sa.Column("instance_id", sa.String(100), server_default="", nullable=False),
        sa.Column("node", sa.String(100), server_default="", nullable=False),
        # done = 正常结束；failed = 异常中断（错误事件后 stop）。
        sa.Column("state", sa.String(16), server_default="done", nullable=False),
        sa.Column("turns", sa.Integer(), server_default="0", nullable=False),
        sa.Column("duration_ms", sa.Integer(), server_default="0", nullable=False),
        sa.Column("ttfa_ms", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_param_session_record_user_id", "param_session_record", ["user_id"])
    op.create_index("ix_param_session_record_state", "param_session_record", ["state"])
    op.create_index("ix_param_session_record_created_at", "param_session_record", ["created_at"])

    op.create_table(
        "param_session_message",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "session_id",
            sa.Integer(),
            sa.ForeignKey("param_session_record.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("ordinal", sa.Integer(), server_default="0", nullable=False),
        # user | assistant | tool
        sa.Column("role", sa.String(16), nullable=False),
        # text | audio
        sa.Column("type", sa.String(16), server_default="text", nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("interrupted", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_param_session_message_session_id", "param_session_message", ["session_id"])
    op.create_index("ix_param_session_message_ordinal", "param_session_message", ["ordinal"])


def downgrade() -> None:
    op.drop_index("ix_param_session_message_ordinal", table_name="param_session_message")
    op.drop_index("ix_param_session_message_session_id", table_name="param_session_message")
    op.drop_table("param_session_message")
    op.drop_index("ix_param_session_record_created_at", table_name="param_session_record")
    op.drop_index("ix_param_session_record_state", table_name="param_session_record")
    op.drop_index("ix_param_session_record_user_id", table_name="param_session_record")
    op.drop_table("param_session_record")
