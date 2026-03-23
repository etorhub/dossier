"""Standalone CLI for pipeline processing. Run in worker container: python -m app.worker_cli <cmd>."""

import logging
import os

import click

from app.cli import run_seed_sources
from app.db import sources as sources_db


@click.group()
def worker_cli() -> None:
    """Pipeline processing commands. Run in worker container only."""


@worker_cli.command("validate-feeds")
def validate_feeds_cmd() -> None:
    """Fetch each active feed, verify it parses, and report status."""
    from app.discovery.feed_detection import validate_feed

    feeds = sources_db.get_all_active_feeds()
    if not feeds:
        click.echo("No active feeds found. Run flask seed-sources first.")
        return

    ok_count = 0
    for feed in feeds:
        result = validate_feed(feed["feed_url"])
        status = "OK" if result["ok"] else f"FAIL: {result.get('error', 'unknown')}"
        if result["ok"]:
            ok_count += 1
        click.echo(f"  {feed['name']} ({feed.get('feed_label', 'main')}): {status}")
        if result["ok"]:
            c = result["completeness_pct"]
            click.echo(f"    items={result['item_count']} completeness={c}%")

    failed = len(feeds) - ok_count
    click.echo(f"Validated {len(feeds)} feeds: {ok_count} OK, {failed} failed.")


@worker_cli.command("score-sources")
def score_sources_cmd() -> None:
    """Compute quality scores for all sources and update the database."""
    from app.discovery.feed_detection import validate_feed
    from app.discovery.scoring import calculate_quality_score
    from app.discovery.validation import check_https

    sources = sources_db.get_all_sources()
    if not sources:
        click.echo("No sources found. Run flask seed-sources first.")
        return

    for source in sources:
        feeds = sources_db.get_feeds_for_source(source["id"])
        if not feeds:
            score = 0.0
        else:
            completeness = 0.0
            articles_total = 0.0
            feed_type = "rss"
            for f in feeds:
                result = validate_feed(f["feed_url"])
                if result["ok"]:
                    cp = result.get("completeness_pct")
                    if cp is not None:
                        completeness = max(completeness, float(cp))
                    ic = result.get("item_count")
                    if ic is not None:
                        articles_total += int(ic)
                    ft = result.get("feed_type")
                    feed_type = ft if isinstance(ft, str) else "rss"
            articles_per_day = articles_total / len(feeds) if feeds else 0.0
            https_ok = check_https(source["domain"])
            score = calculate_quality_score(
                feed_completeness_pct=completeness,
                feed_type=feed_type,
                articles_per_day=articles_per_day,
                https_ok=https_ok,
            )
        sources_db.update_source_score(source["id"], score)
        click.echo(f"  {source['name']}: score={score}")

    click.echo(f"Scored {len(sources)} sources.")


@worker_cli.command("fetch-feeds")
def fetch_feeds_cmd() -> None:
    """Run the feed fetcher once (fetch all due feeds)."""
    from app.scheduler import _run_tracked_job
    from app.feed.orchestrator import fetch_all_due_feeds

    _run_tracked_job("fetch_feeds", fetch_all_due_feeds, trigger="manual")
    click.echo("Fetch job completed. Check ops dashboard for details.")


@worker_cli.command("enrich-articles")
def enrich_articles_cmd() -> None:
    """Extract full article content for pending articles (enrichment job)."""
    from app.scheduler import _run_tracked_job
    from app.extraction.extractor import enrich_all_articles

    _run_tracked_job("enrich_articles", enrich_all_articles, trigger="manual")
    click.echo("Enrichment job completed. Check ops dashboard for details.")


@worker_cli.command("cluster-articles")
def cluster_articles_cmd() -> None:
    """Embed and cluster today's articles (cluster job)."""
    from app.scheduler import _run_tracked_job
    from app.clustering.service import run_cluster_and_embed

    _run_tracked_job("cluster_articles", run_cluster_and_embed, trigger="manual")
    click.echo("Cluster job completed. Check ops dashboard for details.")


@worker_cli.command("review-clustering")
def review_clustering_cmd() -> None:
    """Run the clustering feedback review agent on pending flags (LLM + exclusion rules)."""
    from app.clustering.feedback_agent import run_feedback_review

    result = run_feedback_review()
    click.echo(
        f"Processed {result.rows_processed} feedback row(s), created {result.rules_created} exclusion rule(s), "
        f"retroactive article_pair removals: {result.retroactive_removals}."
    )


@worker_cli.command("apply-clustering-exclusion-rules")
def apply_clustering_exclusion_rules_cmd() -> None:
    """Re-apply active article_pair rules to existing stories (no LLM)."""
    from app.clustering.retroactive_rules import apply_article_pair_rules_retroactively

    n = apply_article_pair_rules_retroactively()
    click.echo(f"Retroactive article_pair enforcement: {n} membership removal(s).")


@worker_cli.command("embedding-status")
@click.option(
    "--compact",
    is_flag=True,
    help="Single-line JSON (for scripts / watch dashboards).",
)
def embedding_status_cmd(compact: bool) -> None:
    """Print embedding queue snapshot (JSON). Use scripts/embed-status.sh for a live TUI."""
    import json

    from app.clustering.embed_status import build_embedding_status

    data = build_embedding_status()
    if compact:
        click.echo(json.dumps(data, separators=(",", ":")))
    else:
        click.echo(json.dumps(data, indent=2, default=str))


@worker_cli.command("rewrite-articles")
def rewrite_articles_cmd() -> None:
    """Rewrite today's articles for all user profiles (rewrite job)."""
    from app.scheduler import _run_tracked_job
    from app.services.rewrite_service import run_rewrite_batch

    try:
        _run_tracked_job("rewrite_articles", run_rewrite_batch, trigger="manual")
    except Exception as e:
        click.echo(f"Rewrite job failed: {e}", err=True)
        raise SystemExit(1)
    click.echo("Rewrite job completed. Check ops dashboard for details.")


@worker_cli.command("run-pipeline")
@click.option(
    "--sources-path",
    type=click.Path(exists=True),
    default=None,
    help="Path to sources.yaml for seed step (default: config/sources.yaml)",
)
def run_pipeline_cmd(sources_path: str | None) -> None:
    """Run the full pipeline once: seed → fetch → enrich → cluster → rewrite."""
    from app.scheduler import _run_tracked_job
    from app.clustering.service import run_cluster_and_embed
    from app.extraction.extractor import enrich_all_articles
    from app.feed.orchestrator import fetch_all_due_feeds
    from app.services.rewrite_service import run_rewrite_batch

    click.echo("Running seed-sources...")
    run_seed_sources(sources_path)
    click.echo("Running fetch...")
    _run_tracked_job("fetch_feeds", fetch_all_due_feeds, trigger="manual")
    click.echo("Running enrichment...")
    _run_tracked_job("enrich_articles", enrich_all_articles, trigger="manual")
    click.echo("Running cluster...")
    _run_tracked_job("cluster_articles", run_cluster_and_embed, trigger="manual")
    click.echo("Running rewrite...")
    try:
        _run_tracked_job("rewrite_articles", run_rewrite_batch, trigger="manual")
    except Exception as e:
        click.echo(f"Rewrite failed: {e}", err=True)
        raise SystemExit(1)
    click.echo("Pipeline complete.")


def main() -> None:
    """Entry point for python -m app.worker_cli."""
    if os.path.exists(".env"):
        from dotenv import load_dotenv

        load_dotenv()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    worker_cli()


if __name__ == "__main__":
    main()
