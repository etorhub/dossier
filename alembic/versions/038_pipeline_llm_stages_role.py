"""Extend dossier_pipeline role to cover all off-host LLM stages

Revision ID: 038
Revises: 037
Create Date: 2026-07-04

Migration 037 scoped `dossier_pipeline` to the rewrite job only. The role now
runs the full set of off-host LLM stages (embed+cluster → rewrite → highlight)
against the NAS's Postgres over a Cloudflare Tunnel — see docs/REMOTE_REWRITE.md.
Highlight only writes `story_rewrites` (already granted in 037). Embed+cluster
need three more grants, added here:

  - UPDATE (embedding, embedding_vec) ON articles — the embed step writes only
    these two columns (column-level grant keeps articles otherwise read-only).
    See app/db/articles.py:update_article_embedding.
  - INSERT ON stories — the cluster step creates new stories (app/db/stories.py).
    (037 already granted SELECT, UPDATE for centroid writes / dissolve.)
  - INSERT ON story_articles — the cluster step adds article memberships.
    (037 already granted SELECT, DELETE.)

Sequences were already granted broadly in 037; job_runs INSERT/UPDATE too. The
role still has no access to users/profiles/settings or to inserting articles.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers
revision: str = "038"
down_revision: str | None = "037"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("GRANT UPDATE (embedding, embedding_vec) ON articles TO dossier_pipeline")
    op.execute("GRANT INSERT ON stories TO dossier_pipeline")
    op.execute("GRANT INSERT ON story_articles TO dossier_pipeline")


def downgrade() -> None:
    op.execute("REVOKE INSERT ON story_articles FROM dossier_pipeline")
    op.execute("REVOKE INSERT ON stories FROM dossier_pipeline")
    op.execute("REVOKE UPDATE (embedding, embedding_vec) ON articles FROM dossier_pipeline")
