"""参数模板表 + 机器平台/驱动列（原型「模板管理」与模板硬件校验的落库）。

Revision ID: 0018_templates
Revises: 0017_backend_metric

`param_template`：模板 CRUD 与「保存为模板」的存储；字段 schema 以
parameter-catalog 为单一事实源，表里只存快照。`param_machine` 补
platform/driver 两列：agent 未上报时 platform 由 gpu 描述推断，驱动为空。
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0018_templates"
down_revision = "0017_backend_metric"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "param_template",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("effect", sa.String(16), server_default="runtime", nullable=False),
        sa.Column("platform", sa.String(16), server_default="gpu", nullable=False),
        sa.Column("status", sa.String(16), server_default="draft", nullable=False),
        sa.Column("scene", sa.String(32), server_default="", nullable=False),
        sa.Column("min_vram_gb", sa.Float(), nullable=True),
        sa.Column("fields_json", sa.JSON(), nullable=False),
        sa.Column("description", sa.String(512), server_default="", nullable=False),
        sa.Column("created_by", sa.String(64), server_default="", nullable=False),
        sa.Column("updated_by", sa.String(64), server_default="", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("name", name="uq_param_template_name"),
    )
    op.create_index("ix_param_template_effect", "param_template", ["effect"])
    op.create_index("ix_param_template_platform", "param_template", ["platform"])
    op.create_index("ix_param_template_status", "param_template", ["status"])

    op.add_column(
        "param_machine", sa.Column("platform", sa.String(16), server_default="gpu", nullable=False)
    )
    op.add_column(
        "param_machine", sa.Column("driver", sa.String(64), server_default="", nullable=False)
    )


def downgrade() -> None:
    op.drop_column("param_machine", "driver")
    op.drop_column("param_machine", "platform")
    op.drop_index("ix_param_template_status", table_name="param_template")
    op.drop_index("ix_param_template_platform", table_name="param_template")
    op.drop_index("ix_param_template_effect", table_name="param_template")
    op.drop_table("param_template")
