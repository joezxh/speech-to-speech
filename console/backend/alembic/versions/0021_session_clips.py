"""会话音频片段表（通话双端 WAV 落库，片段条可回放）。

Revision ID: 0021_session_clips
Revises: 0020_session_message_fields

`param_session_clip`：会话消息行上的音频片段，message_ordinal 与
`param_session_message.ordinal` 同一语义（全局行序）。字节存 bytea
（sqlite 方言为 BLOB），随会话删除级联清理（ON DELETE CASCADE）。
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0021_session_clips"
down_revision = "0020_session_message_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "param_session_clip",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "session_id",
            sa.Integer(),
            sa.ForeignKey("param_session_record.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # 与 param_session_message.ordinal 同一语义：全局行序。
        sa.Column("message_ordinal", sa.Integer(), server_default="0", nullable=False),
        # user | assistant（tool 行没有音频）。
        sa.Column("role", sa.String(16), nullable=False),
        # 前端 turn 标识（itemId / responseId），仅作对账展示，不参与对齐。
        sa.Column("item_ref", sa.String(128), server_default="", nullable=False),
        sa.Column("mime", sa.String(64), server_default="audio/wav", nullable=False),
        sa.Column("sample_rate", sa.Integer(), server_default="24000", nullable=False),
        sa.Column("duration_ms", sa.Integer(), server_default="0", nullable=False),
        sa.Column("size_bytes", sa.Integer(), server_default="0", nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_param_session_clip_session_id", "param_session_clip", ["session_id"])


def downgrade() -> None:
    op.drop_index("ix_param_session_clip_session_id", table_name="param_session_clip")
    op.drop_table("param_session_clip")
