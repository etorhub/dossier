"""Ensure each article appears in at most one story (idempotent clustering).

Revision ID: 020
Revises: 019
Create Date: 2026-03-23

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "020"
down_revision: str | None = "019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Keep a single membership row per article (deterministic: lowest story_id UUID).
    op.execute(
        sa.text(
            """
            DELETE FROM story_articles sa
            WHERE EXISTS (
                SELECT 1 FROM story_articles sa2
                WHERE sa2.article_id = sa.article_id
                  AND sa2.story_id < sa.story_id
            )
            """
        )
    )
    op.drop_index("idx_story_articles_article", table_name="story_articles")
    op.create_index(
        "uq_story_articles_article_id",
        "story_articles",
        ["article_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_story_articles_article_id", table_name="story_articles")
    op.create_index(
        "idx_story_articles_article",
        "story_articles",
        ["article_id"],
        unique=False,
    )
