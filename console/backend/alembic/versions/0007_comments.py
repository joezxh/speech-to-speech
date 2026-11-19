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


def _execute(statement: str) -> None:
    """在线 PostgreSQL 下容错：表尚未创建时跳过 COMMENT，不让迁移整体失败。

    app/models/comments.py 的文案覆盖全部模型表，但其中若干表（如
    param_instance_runtime）要到 0010 才建；0007 先跑时 COMMENT ON 会抛
    UndefinedTable。用 DO block 捕获该异常后静默跳过，等 0010 建成后这些
    表的注释由模型层 create_all / 后续补注释流程处理。
    离线模式（--sql）不能包 DO block，保持原语句由 alembic 原样渲染。
    """
    if op.get_context().as_sql:
        op.execute(sa.text(statement))
        return
    # statement 里的单引号已由 comments._literal 正确转义；这里不再二次转义。
    wrapped = (
        "DO $comments$ BEGIN "
        + statement
        + "; EXCEPTION WHEN undefined_table OR undefined_column THEN NULL; "
          "END $comments$"
    )
    op.execute(sa.text(wrapped))


def upgrade() -> None:
    # op.get_context().dialect 在在线与离线（upgrade head --sql）两种模式下都可用；
    # 不能用 op.get_bind()，离线模式没有连接。
    for statement in comment_statements(op.get_context().dialect.name):
        _execute(statement)


def downgrade() -> None:
    for statement in drop_comment_statements(op.get_context().dialect.name):
        _execute(statement)
