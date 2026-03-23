"""Add query-aligned indexes for feed, pipeline, ops, and rewrite queue.

Revision ID: 019
Revises: 018
Create Date: 2026-03-23

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "019"
down_revision: str | None = "018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "idx_story_articles_article",
        "story_articles",
        ["article_id"],
        unique=False,
    )
    op.create_index(
        "idx_articles_pub_no_embedding",
        "articles",
        ["published_at"],
        unique=False,
        postgresql_ops={"published_at": "DESC"},
        postgresql_where=sa.text("embedding IS NULL"),
    )
    op.create_index(
        "idx_articles_pub_has_embedding",
        "articles",
        ["published_at"],
        unique=False,
        postgresql_ops={"published_at": "DESC"},
        postgresql_where=sa.text("embedding IS NOT NULL"),
    )
    op.drop_index("idx_articles_extraction_status", table_name="articles")
    op.create_index(
        "idx_articles_pending_fetch",
        "articles",
        ["fetched_at"],
        unique=False,
        postgresql_ops={"fetched_at": "DESC NULLS LAST"},
        postgresql_where=sa.text("extraction_status = 'pending'"),
    )
    op.create_index(
        "idx_stories_created_at",
        "stories",
        ["created_at"],
        unique=False,
        postgresql_ops={"created_at": "DESC"},
    )
    op.create_index(
        "idx_job_runs_started_at",
        "job_runs",
        ["started_at"],
        unique=False,
        postgresql_ops={"started_at": "DESC"},
    )
    op.drop_index("idx_rewrite_requests_status", table_name="rewrite_requests")
    op.create_index(
        "idx_rewrite_requests_status_created",
        "rewrite_requests",
        ["status", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_rewrite_requests_status_created", table_name="rewrite_requests")
    op.create_index(
        "idx_rewrite_requests_status",
        "rewrite_requests",
        ["status"],
        unique=False,
    )
    op.drop_index("idx_job_runs_started_at", table_name="job_runs")
    op.drop_index("idx_stories_created_at", table_name="stories")
    op.drop_index("idx_articles_pending_fetch", table_name="articles")
    op.create_index(
        "idx_articles_extraction_status",
        "articles",
        ["extraction_status"],
        unique=False,
    )
    op.drop_index("idx_articles_pub_has_embedding", table_name="articles")
    op.drop_index("idx_articles_pub_no_embedding", table_name="articles")
    op.drop_index("idx_story_articles_article", table_name="story_articles")
