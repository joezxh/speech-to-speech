"""回调子系统：callback_target + callback_delivery_log（spec 2026-11-25 §8.1）。

Revision ID: 0015_callback_subsystem
Revises: 0014_comments_backfill

两张新表晚于 0014 的注释回填建成，因此在建表后对 PostgreSQL 补挂中文注释
（文案与模型层 create_all 同源，见 app/models/comments.py）；SQLite 不支持
COMMENT ON，该方言下跳过（离线 init-sqlite.sql 不产生 COMMENT 语句）。
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op
from app.models.comments import comment_statements

revision = "0015_callback_subsystem"
down_revision = "0014_comments_backfill"
branch_labels = None
depends_on = None

_COMMENT_TABLES = ("callback_target", "callback_delivery_log")


def upgrade() -> None:
    op.create_table(
        "callback_target",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("target_type", sa.String(16), nullable=False),
        sa.Column("base_url", sa.String(512), nullable=False),
        sa.Column("auth_type", sa.String(16), server_default="none", nullable=False),
        sa.Column("auth_header_name", sa.String(128), nullable=True),
        sa.Column("auth_token", sa.String(512), server_default="", nullable=False),
        sa.Column("extra_headers", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("timeout_ms", sa.Integer(), server_default="3000", nullable=False),
        sa.Column("retry_max_attempts", sa.Integer(), server_default="3", nullable=False),
        sa.Column("retry_backoff_ms", sa.Integer(), server_default="500", nullable=False),
        sa.Column("events", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("filters", sa.JSON(), nullable=True),
        sa.Column("enabled", sa.Boolean(), server_default="1", nullable=False),
        sa.Column("updated_by", sa.String(64), server_default="", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("name", name="uq_callback_target_name"),
    )
    op.create_table(
        "callback_delivery_log",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "target_id", sa.Integer(),
            sa.ForeignKey("callback_target.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column("event_type", sa.String(32), nullable=False),
        sa.Column("triggered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("request_url", sa.String(1024), nullable=False),
        sa.Column("request_payload", sa.Text(), server_default="", nullable=False),
        sa.Column("attempt", sa.Integer(), server_default="1", nullable=False),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("response_snippet", sa.Text(), server_default="", nullable=False),
        sa.Column("duration_ms", sa.Integer(), server_default="0", nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("error", sa.String(1024), server_default="", nullable=False),
    )
    op.create_index("ix_cdl_target_id", "callback_delivery_log", ["target_id"])
    op.create_index("ix_cdl_triggered_at", "callback_delivery_log", ["triggered_at"])
    op.create_index("ix_cdl_status", "callback_delivery_log", ["status"])
    # 新表建于 0014 注释回填之后：仅对这两张表补挂中文注释（PG）。
    for statement in comment_statements(op.get_context().dialect.name):
        if any(f'"{table}"' in statement for table in _COMMENT_TABLES):
            op.execute(sa.text(statement))


def downgrade() -> None:
    op.drop_index("ix_cdl_status", table_name="callback_delivery_log")
    op.drop_index("ix_cdl_triggered_at", table_name="callback_delivery_log")
    op.drop_index("ix_cdl_target_id", table_name="callback_delivery_log")
    op.drop_table("callback_delivery_log")
    op.drop_table("callback_target")
