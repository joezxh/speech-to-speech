"""Per-backend call metric table (STT/LLM/TTS counters from agent heartbeats).

Revision ID: 0017_backend_metric
Revises: 0016_agent_config_hash_len

`param_backend_metric`：agent 心跳 tokens.backends{} 的落点（窗口增量，
负值钳 0 由仓储层保证）。不建 FK：机器/负载删除后历史仍可读，与
param_token_metric 同约定。
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0017_backend_metric"
down_revision = "0016_agent_config_hash_len"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "param_backend_metric",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("machine_id", sa.String(64), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("engine", sa.String(64), server_default="", nullable=False),
        sa.Column("model", sa.String(128), server_default="", nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("calls", sa.Integer(), server_default="0", nullable=False),
        sa.Column("errors", sa.Integer(), server_default="0", nullable=False),
        sa.Column("latency_ms_sum", sa.Integer(), server_default="0", nullable=False),
        sa.Column("window_s", sa.Integer(), server_default="0", nullable=False),
        sa.Column("reported_by", sa.String(64), server_default="agent", nullable=False),
    )
    op.create_index("ix_param_backend_metric_machine_id", "param_backend_metric", ["machine_id"])
    op.create_index("ix_param_backend_metric_observed_at", "param_backend_metric", ["observed_at"])


def downgrade() -> None:
    op.drop_index("ix_param_backend_metric_observed_at", table_name="param_backend_metric")
    op.drop_index("ix_param_backend_metric_machine_id", table_name="param_backend_metric")
    op.drop_table("param_backend_metric")
