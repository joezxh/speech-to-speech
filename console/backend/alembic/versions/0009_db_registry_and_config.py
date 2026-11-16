"""DB-backed registry state and console config (spec 2026-11-17 §2).

Revision ID: 0009_db_registry_and_config
Revises: 0008_proxy_metrics

三张新表，职责分离（沿用「槽位语义与代理语义不混一张表」的既有口径）：

- `param_config`：控制台配置项登记表（库优先于环境变量）。
- `param_instance_runtime`：实例运行时状态（健康五态、槽位、能力指纹、占位数）。
- `param_allocator_lease`：选台占位租约明细（pending 待连接 / held 会话占用）。

都不建 FK：实例删除后历史仍可读，与 `param_instance_metric` 既有做法一致。
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0009_db_registry_and_config"
down_revision = "0008_proxy_metrics"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "param_config",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("config_key", sa.String(128), nullable=False),
        sa.Column("value", sa.String(1024), server_default="", nullable=False),
        sa.Column("value_type", sa.String(16), server_default="str", nullable=False),
        sa.Column("section", sa.String(32), server_default="console", nullable=False),
        sa.Column("description", sa.String(255), server_default="", nullable=False),
        sa.Column("restart_required", sa.Boolean(), server_default="0", nullable=False),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("updated_by", sa.String(64), server_default="", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("config_key", name="uq_param_config_key"),
    )
    op.create_table(
        "param_instance_runtime",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("instance_id", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), server_default="unknown", nullable=False),
        sa.Column("pool_size", sa.Integer(), nullable=True),
        sa.Column("in_use", sa.Integer(), nullable=True),
        sa.Column("stuck", sa.Integer(), nullable=True),
        sa.Column("probe_ms", sa.Integer(), nullable=True),
        sa.Column("capabilities", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("capability_issues", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("consecutive_failures", sa.Integer(), server_default="0", nullable=False),
        sa.Column("consecutive_successes", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_error", sa.String(255), server_default="", nullable=False),
        sa.Column("probe_history", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("reserved", sa.Integer(), server_default="0", nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("observed_by", sa.String(64), server_default="", nullable=False),
        sa.UniqueConstraint("instance_id", name="uq_param_instance_runtime_instance_id"),
    )
    op.create_table(
        "param_allocator_lease",
        sa.Column("lease_key", sa.String(128), primary_key=True),
        sa.Column("instance_id", sa.String(64), nullable=False),
        sa.Column("state", sa.String(16), server_default="pending", nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("console_id", sa.String(64), server_default="", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    # 读法：某实例上有几条租约、哪些还等着回收。
    op.create_index("ix_param_allocator_lease_instance_id", "param_allocator_lease", ["instance_id"])
    op.create_index("ix_param_allocator_lease_state", "param_allocator_lease", ["state"])
    op.create_index("ix_param_allocator_lease_expires_at", "param_allocator_lease", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_param_allocator_lease_expires_at", table_name="param_allocator_lease")
    op.drop_index("ix_param_allocator_lease_state", table_name="param_allocator_lease")
    op.drop_index("ix_param_allocator_lease_instance_id", table_name="param_allocator_lease")
    op.drop_table("param_allocator_lease")
    op.drop_table("param_instance_runtime")
    op.drop_table("param_config")
