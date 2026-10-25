"""Instance registry + metrics (spec 2026-10-26 §5).

Revision ID: 0005_instances
Revises: 0004_turn_latency
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0005_instances"
down_revision = "0004_turn_latency"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "param_instance",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("instance_id", sa.String(64), nullable=False),
        sa.Column("base_url", sa.String(255), nullable=False),
        sa.Column("weight", sa.Integer(), server_default="1", nullable=False),
        sa.Column("max_sessions_hint", sa.Integer(), nullable=True),
        sa.Column("labels_json", sa.JSON(), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default="1", nullable=False),
        sa.Column("drain_requested", sa.Boolean(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by", sa.String(64), server_default="", nullable=False),
        sa.UniqueConstraint("instance_id", name="uq_param_instance_instance_id"),
    )
    op.create_table(
        "param_instance_metric",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("instance_id", sa.String(64), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("observed_by", sa.String(64), nullable=False),
        sa.Column("kind", sa.String(16), server_default="sample", nullable=False),
        sa.Column("size", sa.Integer(), nullable=True),
        sa.Column("in_use", sa.Integer(), nullable=True),
        sa.Column("free", sa.Integer(), nullable=True),
        sa.Column("stuck", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("probe_ms", sa.Integer(), nullable=True),
        sa.Column("alloc_ok", sa.Integer(), server_default="0", nullable=False),
        sa.Column("alloc_fail_no_instance", sa.Integer(), server_default="0", nullable=False),
        sa.Column("alloc_fail_instance_503", sa.Integer(), server_default="0", nullable=False),
        sa.Column("evict_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("recover_count", sa.Integer(), server_default="0", nullable=False),
    )
    # 面板读法永远是 "这个实例、这个窗口、最新优先"。
    op.create_index("ix_param_instance_metric_instance_id", "param_instance_metric", ["instance_id"])
    op.create_index("ix_param_instance_metric_observed_at", "param_instance_metric", ["observed_at"])


def downgrade() -> None:
    op.drop_index("ix_param_instance_metric_observed_at", table_name="param_instance_metric")
    op.drop_index("ix_param_instance_metric_instance_id", table_name="param_instance_metric")
    op.drop_table("param_instance_metric")
    op.drop_table("param_instance")
