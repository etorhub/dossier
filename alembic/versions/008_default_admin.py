"""Seed default admin user (admin@admin.com / admin).

Revision ID: 008
Revises: 007
Create Date: 2025-03-16

"""

from collections.abc import Sequence

import bcrypt
from sqlalchemy import text

from alembic import op

revision: str = "008"
down_revision: str | None = "007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Create default admin user if not exists. Idempotent."""
    conn = op.get_bind()
    password_hash = bcrypt.hashpw(b"admin", bcrypt.gensalt()).decode("utf-8")

    conn.execute(
        text("""
            INSERT INTO users (email, password_hash, is_admin)
            VALUES ('admin@admin.com', :password_hash, true)
            ON CONFLICT (email) DO UPDATE SET is_admin = true
        """),
        {"password_hash": password_hash},
    )


def downgrade() -> None:
    """Remove default admin user."""
    conn = op.get_bind()
    conn.execute(text("DELETE FROM users WHERE email = 'admin@admin.com'"))
