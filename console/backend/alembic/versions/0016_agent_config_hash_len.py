"""扩 param_agent_config_version.yaml_hash 到 80 字符。

Revision ID: 0016_agent_config_hash_len
Revises: 0015_callback_subsystem

背景：agent 配置下发链路的 ack 成功标记是前缀 hack——
`agent_config_service.ack` 把 64 位 sha256 写成 `"ack:" + hash`（4 + 64 = 68 字符），
落在 varchar(64) 列上触发 StringDataRightTruncation，agent 的 config/ack
永久 500（2026-11-27 在 40.30 部署实测）。列扩到 80，模型同步改 String(80)。
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0016_agent_config_hash_len"
down_revision = "0015_callback_subsystem"
branch_labels = None
depends_on = None

# SQLite 的 batch alter_column 在离线（--sql）模式下无法反射表结构，必须传
# copy_from。两份定义与 0010 建表时/扩列后的真实列集一致，勿随意增删列。
_OLD_TABLE = sa.Table(
    "param_agent_config_version",
    sa.MetaData(),
    sa.Column("machine_id", sa.String(64), primary_key=True),
    sa.Column("config_version", sa.Integer, primary_key=True),
    sa.Column("yaml_hash", sa.String(64), nullable=False, server_default=""),
    sa.Column("yaml_text", sa.Text, nullable=False),
    sa.Column("rendered_at", sa.DateTime(timezone=True), nullable=False),
)

_NEW_TABLE = sa.Table(
    "param_agent_config_version",
    sa.MetaData(),
    sa.Column("machine_id", sa.String(64), primary_key=True),
    sa.Column("config_version", sa.Integer, primary_key=True),
    sa.Column("yaml_hash", sa.String(80), nullable=False, server_default=""),
    sa.Column("yaml_text", sa.Text, nullable=False),
    sa.Column("rendered_at", sa.DateTime(timezone=True), nullable=False),
)


def upgrade() -> None:
    # SQLite 的 VARCHAR(64) 本就不强制长度（类型亲和性），扩列无意义；且 batch
    # 的 move-and-copy 在离线（--sql）渲染会生成临时表 CREATE，破坏 schema-sql
    # 静态闸的 CREATE TABLE 计数。SQLite 下本迁移 no-op，仅 PostgreSQL 扩列。
    if op.get_context().dialect.name == "sqlite":
        return
    with op.batch_alter_table("param_agent_config_version", copy_from=_OLD_TABLE) as batch:
        batch.alter_column(
            "yaml_hash",
            type_=sa.String(80),
            existing_type=sa.String(64),
            existing_nullable=False,
            existing_server_default="",
        )


def downgrade() -> None:
    if op.get_context().dialect.name == "sqlite":
        return
    # 先摘除 ack: 前缀（摘除后回 64 位摘要），避免超长行阻断缩列。
    op.execute(
        sa.text(
            "UPDATE param_agent_config_version SET yaml_hash = substr(yaml_hash, 5) "
            "WHERE yaml_hash LIKE 'ack:%'"
        )
    )
    with op.batch_alter_table("param_agent_config_version", copy_from=_NEW_TABLE) as batch:
        batch.alter_column(
            "yaml_hash",
            type_=sa.String(64),
            existing_type=sa.String(80),
            existing_nullable=False,
            existing_server_default="",
        )
