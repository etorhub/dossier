"""Add pgvector embedding columns to articles and stories

Revision ID: e6f7a8b9c0d1
Revises: d5e6f7a8b9c0
Create Date: 2026-03-25

Adds:
  articles.embedding_vec  vector(768)   — dual-write alongside JSONB embedding
  stories.centroid_vec    vector(768)   — dual-write alongside JSONB centroid_embedding

Backfills both from their JSONB counterparts.

Creates an IVFFlat cosine index on stories.centroid_vec.  Enable the ANN path by
setting processing.cluster_use_ivfflat: true in config once stories > ~500.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers
revision: str = "e6f7a8b9c0d1"
down_revision: str | None = "d5e6f7a8b9c0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.add_column(
        "articles",
        sa.Column("embedding_vec", sa.Text(), nullable=True),  # stored as vector type
    )
    op.add_column(
        "stories",
        sa.Column("centroid_vec", sa.Text(), nullable=True),  # stored as vector type
    )

    # Alter to actual vector type after adding (SA doesn't know the vector type)
    op.execute("ALTER TABLE articles ALTER COLUMN embedding_vec TYPE vector(768) USING NULL")
    op.execute("ALTER TABLE stories ALTER COLUMN centroid_vec TYPE vector(768) USING NULL")

    # Backfill from JSONB (only rows with the right dimension)
    op.execute(
        """
        UPDATE articles
        SET embedding_vec = embedding::text::vector
        WHERE embedding IS NOT NULL
          AND jsonb_typeof(embedding) = 'array'
          AND jsonb_array_length(embedding) = 768
        """
    )
    op.execute(
        """
        UPDATE stories
        SET centroid_vec = centroid_embedding::text::vector
        WHERE centroid_embedding IS NOT NULL
          AND jsonb_typeof(centroid_embedding) = 'array'
          AND jsonb_array_length(centroid_embedding) = 768
        """
    )

    # IVFFlat cosine index — enable with cluster_use_ivfflat: true when stories > 500
    op.execute(
        """
        CREATE INDEX idx_stories_centroid_vec_cosine
        ON stories USING ivfflat (centroid_vec vector_cosine_ops)
        WITH (lists = 100)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_stories_centroid_vec_cosine")
    op.drop_column("stories", "centroid_vec")
    op.drop_column("articles", "embedding_vec")
