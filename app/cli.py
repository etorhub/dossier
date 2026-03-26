"""Flask CLI commands for web/admin. Processing commands live in app.worker_cli."""

import click

from app.config import load_sources
from app.db import sources as sources_db


def run_seed_sources(sources_path: str | None = None) -> None:
    """Load config/sources.yaml into news_sources and source_feeds tables.

    Shared by CLI and run-pipeline."""
    sources = load_sources(sources_path)
    if not sources:
        click.echo("No sources found in YAML.")
        return

    for s in sources:
        source_row = {
            "id": s["id"],
            "domain": s["domain"],
            "name": s["name"],
            "description": s.get("description"),
            "homepage_url": s["homepage_url"],
            "country_code": s["country_code"],
            "region": s.get("region"),
            "languages": s["languages"],
            "quality_score": None,
            "is_verified": False,
            "full_text_available": s.get("full_text", False),
            "status": "active",
            "last_checked_at": None,
        }
        sources_db.upsert_source(source_row)
        sources_db.delete_feeds_for_source(s["id"])
        for f in s.get("feeds", []):
            feed_row = {
                "source_id": s["id"],
                "feed_type": f.get("type", "rss"),
                "feed_url": f["url"],
                "feed_label": f.get("label"),
            }
            sources_db.insert_feed(feed_row)
        click.echo(f"  Seeded: {s['name']} ({s['id']})")

    click.echo(f"Seeded {len(sources)} sources.")


@click.command("seed-sources")
@click.option(
    "--sources-path",
    type=click.Path(exists=True),
    default=None,
    help="Path to sources.yaml (default: config/sources.yaml)",
)
def seed_sources(sources_path: str | None) -> None:
    """Load config/sources.yaml into news_sources and source_feeds tables."""
    run_seed_sources(sources_path)


@click.command("make-admin")
@click.argument("email", type=str)
def make_admin(email: str) -> None:
    """Grant admin privileges to a user by email."""
    from app.db import users as db_users

    user = db_users.get_user_by_email(email.strip())
    if not user:
        click.echo(f"User not found: {email}")
        raise SystemExit(1)
    db_users.set_admin(user["id"], True)
    click.echo(f"Granted admin to {email}")


@click.command("show-rewrite-failures")
@click.option("--hours", default=24, help="Look back N hours (default: 24)")
@click.option("--limit", default=50, help="Max failures to show (default: 50)")
def show_rewrite_failures(hours: int, limit: int) -> None:
    """List recent cluster rewrite failures with reasons (for diagnostics)."""
    from app.db import admin as admin_db

    failures = admin_db.get_recent_rewrite_failures(hours=hours, limit=limit)
    if not failures:
        click.echo(f"No rewrite failures in the last {hours} hours.")
        return

    click.echo(f"Rewrite failures (last {hours} hours): {len(failures)}")
    click.echo()
    for f in failures:
        reason = f.get("error_message") or "(reason not stored — failures before error tracking)"
        created = f.get("created_at")
        ts = created.strftime("%Y-%m-%d %H:%M") if created else "—"
        click.echo("  {}  {}".format(ts, f.get("cluster_id", "?")[:8]))
        click.echo("    %s" % (reason[:100] + "…" if len(str(reason)) > 100 else reason))
        click.echo()
