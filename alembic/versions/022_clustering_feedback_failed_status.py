"""Mark erroneous clustering_feedback rows as failed (retryable).

Revision ID: 022
Revises: 021
Create Date: 2026-03-23

Previously the review agent set status=reviewed for LLM/parse/internal errors.
Those rows are updated to status=failed so review-clustering will retry them.

"""

from collections.abc import Sequence

from alembic import op

revision: str = "022"
down_revision: str | None = "021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE clustering_feedback
        SET status = 'failed'
        WHERE status = 'reviewed'
          AND (
            agent_analysis LIKE 'LLM error:%'
            OR agent_analysis LIKE 'Unparseable LLM output%'
            OR agent_analysis = 'Internal error during review (see worker logs).'
            OR agent_analysis LIKE 'Article not found in database.%'
            OR agent_analysis LIKE 'KeyError:%'
            OR agent_analysis LIKE '%KeyError%'
          )
        """
    )


def downgrade() -> None:
    # Cannot reliably restore which failed rows were wrongly reviewed; no-op.
    pass
