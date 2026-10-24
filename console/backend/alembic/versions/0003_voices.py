"""Voices table (spec §3.11.3). Same database as `param_*`, different table."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0003_voices"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "voices",
        sa.Column("id", sa.String(26), primary_key=True),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("backend", sa.String(16), nullable=False),
        sa.Column("language", sa.String(16), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="draft"),
        sa.Column("audio_relpath", sa.String(255), nullable=True),
        sa.Column("audio_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("audio_seconds", sa.Float(), nullable=False, server_default="0"),
        sa.Column("trim_start_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("trim_end_ms", sa.Integer(), nullable=True),
        sa.Column("ref_text", sa.Text(), nullable=True),
        sa.Column("instruct", sa.Text(), nullable=True),
        sa.Column("spk_relpath", sa.String(255), nullable=True),
        sa.Column("rvq_relpath", sa.String(255), nullable=True),
        sa.Column("error_code", sa.String(32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_by", sa.String(64), nullable=False),
        sa.Column("consent_ack_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("retention_days", sa.Integer(), nullable=False, server_default="30"),
        sa.UniqueConstraint("name", name="uq_voices_name"),
    )
    op.create_index("ix_voices_status", "voices", ["status"])


def downgrade() -> None:
    op.drop_index("ix_voices_status", table_name="voices")
    op.drop_table("voices")
