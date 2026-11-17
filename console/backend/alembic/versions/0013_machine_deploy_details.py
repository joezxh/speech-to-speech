"""机器部署详情：agent 上报的节点资源与部署参数快照。

Revision ID: 0013_machine_deploy_details
Revises: 0012_workload_observability
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0013_machine_deploy_details"
down_revision = "0012_workload_observability"
branch_labels = None
depends_on = None

COLUMNS = [
    ("gpu_util_pct", sa.Integer(), None),
    ("cpu_pct", sa.Float(), None),
    ("load_avg", sa.JSON(), sa.text("'[]'")),
    ("mem_total_gb", sa.Float(), None),
    ("mem_used_gb", sa.Float(), None),
    ("mem_pct", sa.Float(), None),
    ("gpu_mem_used_gb", sa.Float(), None),
    ("gpu_mem_total_gb", sa.Float(), None),
    ("pipeline_vram_gb", sa.Float(), None),
    ("collected_at", sa.String(40), sa.text("''")),
    ("deployment_json", sa.JSON(), sa.text("'{}'")),
]


def upgrade() -> None:
    for name, type_, default in COLUMNS:
        op.add_column(
            "param_machine",
            sa.Column(name, type_, nullable=default is None, server_default=default),
        )


def downgrade() -> None:
    for name, _, _ in reversed(COLUMNS):
        op.drop_column("param_machine", name)
