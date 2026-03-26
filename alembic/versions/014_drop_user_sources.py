"""Drop user_sources table now that per-user source selection is removed.

Revision ID: 014_drop_user_sources
Revises: 014
Create Date: 2026-03-17
"""

from collections.abc import Sequence

from alembic import op

revision: str = "014_drop_user_sources"
down_revision: str | None = "014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_table("user_sources")


def downgrade() -> None:
    # Recreate user_sources table with the original schema.
    import sqlalchemy as sa

    op.create_table(
        "user_sources",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "source_id"),
    )
