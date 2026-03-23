"""Add job_runs.log_path for per-run log files (ops dashboard).

Revision ID: 023
Revises: 022
Create Date: 2026-03-23

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "023"
down_revision: str | None = "022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "job_runs",
        sa.Column("log_path", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("job_runs", "log_path")
