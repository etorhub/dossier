"""Add coherence_failed and coherence_reason to stories

Revision ID: f0a1b2c3d4e5
Revises: e6f7a8b9c0d1
Create Date: 2026-03-26

When the rewrite LLM determines that a story's clustered articles cover unrelated
events (INCOHERENT: signal), the story is dissolved: its story_articles rows are
deleted and it is marked coherence_failed=true. The story row is kept for audit.
coherence_reason records the LLM's explanation (one sentence, English).
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f0a1b2c3d4e5"
down_revision: str | None = "e6f7a8b9c0d1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "stories",
        sa.Column("coherence_failed", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column(
        "stories",
        sa.Column("coherence_reason", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("stories", "coherence_reason")
    op.drop_column("stories", "coherence_failed")
