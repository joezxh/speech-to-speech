"""前台设置表（对话态热更参数的账号级取值）。

Revision ID: 0023_front_settings
Revises: 0022_tools
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0023_front_settings"
down_revision = "0022_tools"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "param_front_setting",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("config_key", sa.String(128), nullable=False),
        sa.Column("value", sa.String(2048), server_default="", nullable=False),
        sa.Column("value_type", sa.String(16), server_default="str", nullable=False),
        sa.Column("updated_by", sa.String(64), server_default="", nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("config_key", name="uq_param_front_setting_key"),
    )


def downgrade() -> None:
    op.drop_table("param_front_setting")
