"""Clustering feedback and exclusion rules for mis-clustered articles.

Revision ID: 021
Revises: 020
Create Date: 2026-03-23

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID

from alembic import op

revision: str = "021"
down_revision: str | None = "020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "clustering_feedback",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("article_id", sa.Text(), nullable=False),
        sa.Column("story_id", UUID(as_uuid=True), nullable=False),
        sa.Column("similarity_at_flag", sa.Float(), nullable=True),
        sa.Column("article_embedding_snapshot", JSONB(), nullable=True),
        sa.Column("story_centroid_snapshot", JSONB(), nullable=True),
        sa.Column(
            "status",
            sa.Text(),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column("agent_analysis", sa.Text(), nullable=True),
        sa.Column("agent_recommendation", sa.Text(), nullable=True),
        sa.Column(
            "flagged_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("reviewed_at", sa.TIMESTAMP(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["article_id"], ["articles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["story_id"], ["stories.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_clustering_feedback_status",
        "clustering_feedback",
        ["status"],
    )
    op.create_index(
        "ix_clustering_feedback_flagged_at",
        "clustering_feedback",
        ["flagged_at"],
    )

    op.create_table(
        "clustering_exclusion_rules",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("feedback_id", UUID(as_uuid=True), nullable=True),
        sa.Column("rule_type", sa.Text(), nullable=False),
        sa.Column("rule_data", JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("description", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["feedback_id"], ["clustering_feedback.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_clustering_exclusion_rules_active",
        "clustering_exclusion_rules",
        ["active"],
    )


def downgrade() -> None:
    op.drop_index("ix_clustering_exclusion_rules_active", table_name="clustering_exclusion_rules")
    op.drop_table("clustering_exclusion_rules")
    op.drop_index("ix_clustering_feedback_flagged_at", table_name="clustering_feedback")
    op.drop_index("ix_clustering_feedback_status", table_name="clustering_feedback")
    op.drop_table("clustering_feedback")
