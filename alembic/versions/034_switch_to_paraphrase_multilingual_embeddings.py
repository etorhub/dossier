"""Switch embedding model from bge-m3 (1024-dim) to paraphrase-multilingual (768-dim)

Revision ID: 034
Revises: 033
Create Date: 2026-06-27

BGE-M3 (567M params) is too slow for CPU-only inference on the NAS (UGreen DSP
2800) — observed ~30s per single-article embed call, making the daily backlog
take hours to clear. paraphrase-multilingual (278M params, sentence-transformers
paraphrase-multilingual-mpnet-base-v2) still covers Catalan/Spanish well enough
for clustering similarity and is roughly half the size.

Changes:
  articles.embedding_vec  vector(1024) →  vector(768)  (nulled; re-embedded by worker)
  stories.centroid_vec    vector(1024) →  vector(768)  (nulled; recomputed after re-embed)
  articles.embedding      JSONB        →  NULL          (stale 1024-dim vectors cleared)
  stories.centroid_embedding JSONB     →  NULL          (stale 1024-dim centroids cleared)

After running this migration start the worker — the embed job will re-embed all
articles with paraphrase-multilingual and the clustering job will recompute story
centroids.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers
revision: str = "034"
down_revision: str | None = "033"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Drop the IVFFlat index before altering column type
    op.execute("DROP INDEX IF EXISTS idx_stories_centroid_vec_cosine")

    # Resize vector columns to 768 dims (USING NULL clears existing values)
    op.execute("ALTER TABLE articles ALTER COLUMN embedding_vec TYPE vector(768) USING NULL")
    op.execute("ALTER TABLE stories ALTER COLUMN centroid_vec TYPE vector(768) USING NULL")

    # Clear stale 1024-dim JSONB embeddings so the worker re-embeds everything
    op.execute("UPDATE articles SET embedding = NULL")
    op.execute("UPDATE stories SET centroid_embedding = NULL")

    # Recreate the IVFFlat cosine index for the new 768-dim vectors
    op.execute(
        """
        CREATE INDEX idx_stories_centroid_vec_cosine
        ON stories USING ivfflat (centroid_vec vector_cosine_ops)
        WITH (lists = 100)
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_stories_centroid_vec_cosine")
    op.execute("ALTER TABLE articles ALTER COLUMN embedding_vec TYPE vector(1024) USING NULL")
    op.execute("ALTER TABLE stories ALTER COLUMN centroid_vec TYPE vector(1024) USING NULL")
    op.execute("UPDATE articles SET embedding = NULL")
    op.execute("UPDATE stories SET centroid_embedding = NULL")
    op.execute(
        """
        CREATE INDEX idx_stories_centroid_vec_cosine
        ON stories USING ivfflat (centroid_vec vector_cosine_ops)
        WITH (lists = 100)
        """
    )
