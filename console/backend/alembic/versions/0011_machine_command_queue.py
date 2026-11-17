"""机器命令队列：console 下发、agent 拉取并回执的反向通道。

Revision ID: 0011_machine_command_queue
Revises: 0010_console_lb_backbone

不建 FK：machine_id 是软关联（机器删除后命令历史仍可读）。
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0011_machine_command_queue"
down_revision = "0010_console_lb_backbone"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "param_machine_command",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("command_id", sa.String(64), nullable=False),
        sa.Column("machine_id", sa.String(64), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("payload", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("status", sa.String(16), server_default="pending", nullable=False),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("error", sa.String(512), server_default="", nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("command_id", name="uq_param_machine_command_command_id"),
    )
    op.create_index("ix_param_machine_command_machine_id", "param_machine_command", ["machine_id"])
    op.create_index("ix_param_machine_command_status", "param_machine_command", ["status"])
    op.create_index("ix_param_machine_command_expires_at", "param_machine_command", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_param_machine_command_expires_at", table_name="param_machine_command")
    op.drop_index("ix_param_machine_command_status", table_name="param_machine_command")
    op.drop_index("ix_param_machine_command_machine_id", table_name="param_machine_command")
    op.drop_table("param_machine_command")
