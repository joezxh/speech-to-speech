"""Data-plane proxy metrics (spec 2026-11-16 §6.2).

Revision ID: 0008_proxy_metrics
Revises: 0007_comments
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0008_proxy_metrics"
down_revision = "0007_comments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "param_proxy_metric",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("instance_id", sa.String(64), nullable=False),
        sa.Column("service", sa.String(32), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("observed_by", sa.String(64), server_default="", nullable=False),
        sa.Column("ok", sa.Integer(), server_default="0", nullable=False),
        sa.Column("fail_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("fail_reason", sa.String(64), server_default="", nullable=False),
        sa.Column("duration_ms", sa.Integer(), server_default="0", nullable=False),
    )
    # 面板读法永远是 "这个实例、这个窗口、最新优先"。
    op.create_index("ix_param_proxy_metric_instance_id", "param_proxy_metric", ["instance_id"])
    op.create_index("ix_param_proxy_metric_service", "param_proxy_metric", ["service"])
    op.create_index("ix_param_proxy_metric_observed_at", "param_proxy_metric", ["observed_at"])


def downgrade() -> None:
    op.drop_index("ix_param_proxy_metric_observed_at", table_name="param_proxy_metric")
    op.drop_index("ix_param_proxy_metric_service", table_name="param_proxy_metric")
    op.drop_index("ix_param_proxy_metric_instance_id", table_name="param_proxy_metric")
    op.drop_table("param_proxy_metric")
