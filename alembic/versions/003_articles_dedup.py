"""Add articles dedup (guid, unique on source_id+url), source_feeds etag/last_modified.

Revision ID: 003
Revises: 002
Create Date: 2025-03-16

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "003"
down_revision: str | None = "002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("articles", sa.Column("guid", sa.Text(), nullable=True))
    op.create_unique_constraint("uq_articles_source_url", "articles", ["source_id", "url"])

    op.add_column("source_feeds", sa.Column("etag", sa.Text(), nullable=True))
    op.add_column("source_feeds", sa.Column("last_modified", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("source_feeds", "last_modified")
    op.drop_column("source_feeds", "etag")
    op.drop_constraint("uq_articles_source_url", "articles", type_="unique")
    op.drop_column("articles", "guid")
