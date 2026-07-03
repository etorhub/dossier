"""Add dossier_pipeline role for remote rewrite-job access

Revision ID: 037
Revises: 036
Create Date: 2026-07-03

Scoped role for running the rewrite job (app.worker_cli rewrite-articles) from
outside the NAS's docker network (local machine or an ad-hoc/VPS box), reached
over a Cloudflare Tunnel TCP route rather than exposing the main `dossier` role.

Grants are limited to exactly what app/services/rewrite_service.py's
run_rewrite_batch touches: read articles/stories/story_articles, read+write
story_rewrites, update stories (needs_rewrite/last_rewrite_at/coherence fields
via dissolve_story), delete from story_articles (dissolve_story), and
insert+update job_runs for tracking. No access to users/profiles/settings —
the rewrite job doesn't read per-user data (personalization happens at
render/view time on the already-cached story_rewrites).

The role is created with LOGIN but no password here. Set the password once,
out-of-band, on the NAS after deploying this migration:

    ALTER ROLE dossier_pipeline WITH PASSWORD '<generate one, store in a password manager>';

Never put that password in a migration file or commit it to git. See
docs/REMOTE_REWRITE.md for the full setup (Cloudflare Access + wrapper script).
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers
revision: str = "037"
down_revision: str | None = "036"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'dossier_pipeline') THEN
                CREATE ROLE dossier_pipeline WITH LOGIN;
            END IF;
        END
        $$;
        """
    )
    op.execute("GRANT USAGE ON SCHEMA public TO dossier_pipeline")

    op.execute("GRANT SELECT ON articles TO dossier_pipeline")
    op.execute("GRANT SELECT, UPDATE ON stories TO dossier_pipeline")
    op.execute("GRANT SELECT, DELETE ON story_articles TO dossier_pipeline")
    op.execute("GRANT SELECT, INSERT, UPDATE ON story_rewrites TO dossier_pipeline")
    op.execute("GRANT INSERT, UPDATE ON job_runs TO dossier_pipeline")

    # Sequences backing the SERIAL/BIGSERIAL columns touched above (story_rewrites.id,
    # job_runs.id). Granted broadly (all sequences, not just these two) since sequence
    # values carry no sensitive data and this avoids hardcoding names that could drift
    # if a future migration renames a sequence.
    op.execute("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO dossier_pipeline")


def downgrade() -> None:
    op.execute("REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public FROM dossier_pipeline")
    op.execute("REVOKE ALL PRIVILEGES ON job_runs FROM dossier_pipeline")
    op.execute("REVOKE ALL PRIVILEGES ON story_rewrites FROM dossier_pipeline")
    op.execute("REVOKE ALL PRIVILEGES ON story_articles FROM dossier_pipeline")
    op.execute("REVOKE ALL PRIVILEGES ON stories FROM dossier_pipeline")
    op.execute("REVOKE ALL PRIVILEGES ON articles FROM dossier_pipeline")
    op.execute("REVOKE USAGE ON SCHEMA public FROM dossier_pipeline")
    op.execute("DROP ROLE IF EXISTS dossier_pipeline")
