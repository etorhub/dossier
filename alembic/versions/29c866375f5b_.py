"""empty message

Revision ID: 29c866375f5b
Revises: c1d2e3f4a5b7, c3d4e5f6a7b2
Create Date: 2026-03-25 10:12:30.309124

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '29c866375f5b'
down_revision: Union[str, None] = ('c1d2e3f4a5b7', 'c3d4e5f6a7b2')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
