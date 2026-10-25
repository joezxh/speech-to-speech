"""Turn-latency index (A.17).

`down_revision` is `0003_voices`, not `0001_initial`: `0003_voices` already
hangs off `0001_initial`, and pointing a third migration at `0001_initial`
would give alembic two heads and make `alembic upgrade head` refuse to run.

Revision ID: 0004_turn_latency
Revises: 0003_voices
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0004_turn_latency"
down_revision = "0003_voices"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "turn_latency",
        sa.Column("response_key", sa.String(96), primary_key=True, nullable=False),
        sa.Column("turn_revision", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("turn_id", sa.String(96), nullable=True),
        sa.Column("source", sa.String(16), nullable=False, server_default=""),
        sa.Column("status", sa.String(16), nullable=False, server_default=""),
        sa.Column("smart_status", sa.String(16), nullable=True),
        sa.Column("e2e_ms", sa.Integer(), nullable=True),
        sa.Column("stt_ms", sa.Integer(), nullable=True),
        sa.Column("llm_ms", sa.Integer(), nullable=True),
        sa.Column("tts_ttfa_ms", sa.Integer(), nullable=True),
        sa.Column("vad_decision_ms", sa.Integer(), nullable=True),
        sa.Column("hold_ms", sa.Integer(), nullable=True),
        sa.Column("logged_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("raw_offset", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False),
    )
    # Every read is "this window, newest first"; without it the panel degrades
    # as the index grows, which is the one thing an incident tool cannot do.
    op.create_index("ix_turn_latency_logged_at", "turn_latency", ["logged_at"])


def downgrade() -> None:
    op.drop_index("ix_turn_latency_logged_at", table_name="turn_latency")
    op.drop_table("turn_latency")
