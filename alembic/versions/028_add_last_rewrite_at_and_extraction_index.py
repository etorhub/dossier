"""Add last_rewrite_at to stories; index (extraction_status, fetched_at) on articles

Revision ID: d5e6f7a8b9c0
Revises: 29c866375f5b
Create Date: 2026-03-25

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers
revision: str = "d5e6f7a8b9c0"
down_revision: str | None = "29c866375f5b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "stories",
        sa.Column("last_rewrite_at", sa.TIMESTAMP(timezone=True), nullable=True),
    )
    op.create_index(
        "idx_articles_extraction_status_fetched_at",
        "articles",
        ["extraction_status", "fetched_at"],
    )


def downgrade() -> None:
    op.drop_index("idx_articles_extraction_status_fetched_at", table_name="articles")
    op.drop_column("stories", "last_rewrite_at")
