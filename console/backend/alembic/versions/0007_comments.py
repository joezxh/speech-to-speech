"""表与字段的中文 COMMENT 备注（PostgreSQL 存量库补齐）。

Revision ID: 0007_comments
Revises: 0006_clusters

注释文案来自 app/models/comments.py，与模型层 create_all 共用同一事实源。
SQLite 不支持 COMMENT ON，该方言下本迁移是 no-op（离线 init-sqlite.sql
只记录版本推进，不产生 COMMENT 语句）。
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

from app.models.comments import comment_statements, drop_comment_statements

revision = "0007_comments"
down_revision = "0006_clusters"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # op.get_context().dialect 在在线与离线（upgrade head --sql）两种模式下都可用；
    # 不能用 op.get_bind()，离线模式没有连接。
    for statement in comment_statements(op.get_context().dialect.name):
        op.execute(sa.text(statement))


def downgrade() -> None:
    for statement in drop_comment_statements(op.get_context().dialect.name):
        op.execute(sa.text(statement))
