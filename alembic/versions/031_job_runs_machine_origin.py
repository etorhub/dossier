"""Add origin_hostname, origin_ip, origin_mode to job_runs

Revision ID: 031
Revises: f0a1b2c3d4e5
Create Date: 2026-03-27

Records which machine ran each pipeline job, surfaced in the ops dashboard's
job run history.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "031"
down_revision: str | None = "f0a1b2c3d4e5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("job_runs", sa.Column("origin_hostname", sa.Text(), nullable=True))
    op.add_column("job_runs", sa.Column("origin_ip", sa.Text(), nullable=True))
    op.add_column("job_runs", sa.Column("origin_mode", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("job_runs", "origin_mode")
    op.drop_column("job_runs", "origin_ip")
    op.drop_column("job_runs", "origin_hostname")
