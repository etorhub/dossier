"""Add article_type column to articles

Revision ID: b2c3d4e5f6a1
Revises: 025
Create Date: 2026-03-24

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers
revision: str = "b2c3d4e5f6a1"
down_revision: str | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "articles",
        sa.Column(
            "article_type",
            sa.Text(),
            nullable=False,
            server_default="news",
        ),
    )
    op.create_index(
        "idx_articles_article_type",
        "articles",
        ["article_type"],
    )


def downgrade() -> None:
    op.drop_index("idx_articles_article_type", table_name="articles")
    op.drop_column("articles", "article_type")
