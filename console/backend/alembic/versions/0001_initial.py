"""initial tables

Revision ID: 0001_initial
Revises:
Create Date: 2026-10-24
"""
from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "param_user",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("username", sa.String(64), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("role", sa.String(16), nullable=False, server_default="operator"),
        sa.Column("disabled", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "param_draft",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("profile", sa.String(64), nullable=False, unique=True),
        sa.Column("base_version", sa.Integer, nullable=False, server_default="0"),
        sa.Column("patch", sa.JSON, nullable=False),
        sa.Column("updated_by", sa.String(64), nullable=False, server_default=""),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "param_version",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("profile", sa.String(64), nullable=False),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("note", sa.String(500), nullable=False, server_default=""),
        sa.Column("author", sa.String(64), nullable=False, server_default=""),
        sa.Column("yaml_text", sa.Text, nullable=False, server_default=""),
        sa.Column("yaml_sha256", sa.String(64), nullable=False, server_default=""),
        sa.Column("env_sha256", sa.String(64), nullable=False, server_default=""),
        sa.Column("duration_s", sa.Float, nullable=True),
        sa.Column("rolled_back_to", sa.Integer, nullable=True),
        sa.Column("error_code", sa.String(48), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("profile", "version", name="uq_param_version_profile_version"),
    )
    op.create_table(
        "param_audit",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actor", sa.String(64), nullable=False, server_default=""),
        sa.Column("role", sa.String(16), nullable=False, server_default=""),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("profile", sa.String(64), nullable=False, server_default=""),
        sa.Column("version", sa.Integer, nullable=True),
        sa.Column("fields", sa.JSON, nullable=False),
        sa.Column("result", sa.String(8), nullable=False, server_default="ok"),
        sa.Column("error_code", sa.String(48), nullable=True),
        sa.Column("duration_s", sa.Float, nullable=True),
        sa.Column("request_id", sa.String(64), nullable=False, server_default=""),
    )


def downgrade() -> None:
    op.drop_table("param_audit")
    op.drop_table("param_version")
    op.drop_table("param_draft")
    op.drop_table("param_user")
