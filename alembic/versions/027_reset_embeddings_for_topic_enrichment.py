"""Reset article embeddings to trigger re-embedding with topic-enriched text.

Revision ID: c1d2e3f4a5b7
Revises: b2c3d4e5f6a1
Create Date: 2026-03-24

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers
revision: str = "c1d2e3f4a5b7"
down_revision: str | None = "b2c3d4e5f6a1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Only reset news articles — non-news articles are never embedded.
    op.execute("UPDATE articles SET embedding = NULL WHERE article_type = 'news'")
    # Reset story centroids — they will be recomputed after re-embedding.
    op.execute("UPDATE stories SET centroid_embedding = NULL")


def downgrade() -> None:
    # Embeddings cannot be restored from migration; intentional no-op.
    pass
