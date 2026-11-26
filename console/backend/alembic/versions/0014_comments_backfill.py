"""回填中文 COMMENT：补齐 0007 执行后新建的表与字段。

Revision ID: 0014_comments_backfill
Revises: 0013_machine_deploy_details

背景：0007 执行时只有最初的 9 张表，后续 0008–0013 新建的 15 张表被
DO block 的 undefined_table 分支跳过，导致其表/列没有中文注释。
本迁移在全部模型表建成后，用同一份 `app/models/comments.py` 映射再跑一次，
把 24 张表 / 285 列的注释补齐（幂等：重复执行只是覆盖为相同文案）。

SQLite 不支持 COMMENT ON，该方言下本迁移是 no-op（离线 init-sqlite.sql
只记录版本推进，不产生 COMMENT 语句）。
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op
from app.models.comments import comment_statements, drop_comment_statements

revision = "0014_comments_backfill"
down_revision = "0013_machine_deploy_details"
branch_labels = None
depends_on = None


def _execute(statement: str) -> None:
    """在线 PostgreSQL 下容错：表/列不存在时跳过，不让迁移整体失败。

    离线模式（--sql）不能包 DO block，保持原语句由 Alembic 原样渲染。
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
    for statement in comment_statements(op.get_context().dialect.name):
        _execute(statement)


def downgrade() -> None:
    for statement in drop_comment_statements(op.get_context().dialect.name):
        _execute(statement)
