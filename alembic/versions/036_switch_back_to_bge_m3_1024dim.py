"""Switch embedding model from paraphrase-multilingual (768-dim) back to bge-m3 (1024-dim)

Revision ID: 036
Revises: 035
Create Date: 2026-07-02

Reverting the paraphrase-multilingual workaround (migration 034). That model was chosen
because bge-m3 was too slow on the NAS CPU (~30s/article, causing backlogs). The project
now runs primarily on a local GPU machine (RTX 4070) where bge-m3 is essentially instant.

bge-m3 (BAAI/BGE-M3) is significantly better for Catalan+Spanish cross-lingual clustering:
it produces high cosine similarity for same-event article pairs regardless of source language,
whereas paraphrase-multilingual systematically underscores cross-lingual pairs.

Changes:
  articles.embedding_vec  vector(768)  →  vector(1024)  (nulled; re-embedded by worker)
  stories.centroid_vec    vector(768)  →  vector(1024)  (nulled; recomputed after re-embed)
  articles.embedding      JSONB        →  NULL           (stale 768-dim vectors cleared)
  stories.centroid_embedding JSONB     →  NULL           (stale 768-dim centroids cleared)

After running this migration start the worker — the embed job will re-embed all articles
with bge-m3 and the clustering job will recompute story centroids.

NAS deployment note: bge-m3 is slower on CPU (~30s/article) but fine for steady-state
operation with 10-20 new articles/day. The daily job never runs embedding and rewriting
concurrently, so the 06:00 burst is unaffected.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers
revision: str = "036"
down_revision: str | None = "035"
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
