"""Cluster registry (spec 2026-11-05 §2).

Revision ID: 0006_clusters
Revises: 0005_instances
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0006_clusters"
down_revision = "0005_instances"
branch_labels = None
depends_on = None

# 可重入 seed（spec §2.3）：INSERT … SELECT … WHERE NOT EXISTS，
# 手工补插过 default 行后重跑不中断、不重复插。参数化常量 SQL，无注入面；
# 模块级导出供迁移测试直接复用同一条语句验证幂等。
# 取当前时间按当方言原生函数分派：sqlite 初始化 SQL 闸禁止大写字面量
# `TIMESTAMP` 出现在 sqlite 文件中（test_schema_sql.test_the_dialects_use_their_own_types），
# 而 CURRENT_TIMESTAMP 含该子串；datetime('now') 与 PG now() 语义对齐（均为事务/语句时刻）。
def _seed_sql(dialect_name: str) -> sa.TextClause:
    now = "now()" if dialect_name == "postgresql" else "datetime('now')"
    return sa.text(
        "INSERT INTO param_cluster "
        "(name, registry, policy, note, created_at, updated_at, updated_by) "
        f"SELECT 'default', '', 'least', '', {now}, {now}, 'migration' "
        "WHERE NOT EXISTS (SELECT 1 FROM param_cluster WHERE name = 'default')"
    )


# 测试在 sqlite 内存库上直接复用同一条语句（防漂移：不在测试里复制 SQL）。
SEED_SQL = _seed_sql("sqlite")


def upgrade() -> None:
    op.create_table(
        "param_cluster",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("registry", sa.String(255), server_default="", nullable=False),
        sa.Column("policy", sa.String(16), server_default="least", nullable=False),
        sa.Column("note", sa.String(255), server_default="", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_by", sa.String(64), server_default="", nullable=False),
        sa.UniqueConstraint("name", name="uq_param_cluster_name"),
    )
    # 可重入 seed（spec §2.3）：见模块级 _seed_sql，按当言分派取时函数。
    op.execute(_seed_sql(op.get_context().dialect.name))
    # param_instance 加列：SQLite 下 ADD COLUMN 带 NOT NULL 必须有 server_default，
    # batch_alter_table 兼容 Postgres 与 SQLite 的重建语义。
    with op.batch_alter_table("param_instance") as batch:
        batch.add_column(
            sa.Column("cluster_id", sa.String(64), server_default="default", nullable=False)
        )
    op.create_index("ix_param_instance_cluster_id", "param_instance", ["cluster_id"])


def downgrade() -> None:
    op.drop_index("ix_param_instance_cluster_id", table_name="param_instance")
    with op.batch_alter_table("param_instance") as batch:
        batch.drop_column("cluster_id")
    op.drop_table("param_cluster")
