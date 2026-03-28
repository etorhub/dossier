"""Switch embedding model from nomic-embed-text (768-dim) to bge-m3 (1024-dim)

Revision ID: 032
Revises: 031
Create Date: 2026-03-28

BGE-M3 (BAAI/BGE-M3) is a multilingual embedding model supporting 100+ languages,
including Catalan and Spanish — the two languages used by this project's news sources.
nomic-embed-text is English-first and produces poor cross-lingual similarity scores,
causing CA and ES articles about the same event to miss the clustering threshold.

Changes:
  articles.embedding_vec  vector(768)  →  vector(1024)  (nulled; re-embedded by worker)
  stories.centroid_vec    vector(768)  →  vector(1024)  (nulled; recomputed after re-embed)
  articles.embedding      JSONB        →  NULL           (stale 768-dim vectors cleared)
  stories.centroid_embedding JSONB     →  NULL           (stale 768-dim centroids cleared)

After running this migration start the worker — the embed job will re-embed all articles
with bge-m3 and the clustering job will recompute story centroids.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers
revision: str = "032"
down_revision: str | None = "031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Drop the IVFFlat index before altering column type
    op.execute("DROP INDEX IF EXISTS idx_stories_centroid_vec_cosine")

    # Resize vector columns to 1024 dims (USING NULL clears existing values)
    op.execute("ALTER TABLE articles ALTER COLUMN embedding_vec TYPE vector(1024) USING NULL")
    op.execute("ALTER TABLE stories ALTER COLUMN centroid_vec TYPE vector(1024) USING NULL")

    # Clear stale 768-dim JSONB embeddings so the worker re-embeds everything
    op.execute("UPDATE articles SET embedding = NULL")
    op.execute("UPDATE stories SET centroid_embedding = NULL")

    # Recreate the IVFFlat cosine index for the new 1024-dim vectors
    op.execute(
        """
        CREATE INDEX idx_stories_centroid_vec_cosine
        ON stories USING ivfflat (centroid_vec vector_cosine_ops)
        WITH (lists = 100)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_stories_centroid_vec_cosine")
    op.execute("ALTER TABLE articles ALTER COLUMN embedding_vec TYPE vector(768) USING NULL")
    op.execute("ALTER TABLE stories ALTER COLUMN centroid_vec TYPE vector(768) USING NULL")
    op.execute("UPDATE articles SET embedding = NULL")
    op.execute("UPDATE stories SET centroid_embedding = NULL")
    op.execute(
        """
        CREATE INDEX idx_stories_centroid_vec_cosine
        ON stories USING ivfflat (centroid_vec vector_cosine_ops)
        WITH (lists = 100)
        """
    )
