"""Add reading streak columns to user_profiles

Revision ID: 035
Revises: 034
Create Date: 2026-07-01
"""

from collections.abc import Sequence

from alembic import op

revision: str = "035"
down_revision: str | None = "034"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE user_profiles
          ADD COLUMN reading_streak INT NOT NULL DEFAULT 0,
          ADD COLUMN longest_streak INT NOT NULL DEFAULT 0,
          ADD COLUMN last_read_date DATE
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE user_profiles
          DROP COLUMN IF EXISTS reading_streak,
          DROP COLUMN IF EXISTS longest_streak,
          DROP COLUMN IF EXISTS last_read_date
        """
    )
