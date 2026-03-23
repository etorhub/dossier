"""Add color_scheme to user_profiles

Revision ID: 3f8a2c1e047b
Revises: 023
Create Date: 2026-03-23

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers
revision: str = "024"
down_revision: str | None = "023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "user_profiles",
        sa.Column("color_scheme", sa.String(10), nullable=True, server_default=None),
    )


def downgrade() -> None:
    op.drop_column("user_profiles", "color_scheme")
