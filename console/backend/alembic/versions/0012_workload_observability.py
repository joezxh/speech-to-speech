"""机器负载可观测性：保存 agent 采集的 pipeline 模型与全部参数。

Revision ID: 0012_workload_observability
Revises: 0011_machine_command_queue
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0012_workload_observability"
down_revision = "0011_machine_command_queue"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("param_machine_workload") as batch:
        batch.add_column(
            sa.Column("params_json", sa.JSON(), server_default="{}", nullable=False)
        )


def downgrade() -> None:
    with op.batch_alter_table("param_machine_workload") as batch:
        batch.drop_column("params_json")
