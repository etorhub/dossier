"""APScheduler entry point. Runs in the worker container or natively on Pi/PC.

Use SCHEDULER_MODE to split jobs across machines (see docs/DEPLOYMENT_HYBRID.md):
- light: fetch, enrich, availability (e.g. Raspberry Pi)
- heavy: cluster, rewrite — requires Ollama (e.g. local PC)
- full: all jobs (default; Docker dev)
"""

from __future__ import annotations

import contextlib
import logging
import os
from dataclasses import asdict
from typing import Any, Callable

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.config import load_config
from app.db import admin as admin_db
from app.db import articles as articles_db
from app.extraction.extractor import enrich_all_articles
from app.feed.availability import check_all_feeds_availability
from app.feed.orchestrator import fetch_all_due_feeds

logger = logging.getLogger(__name__)

_VALID_MODES = frozenset({"light", "heavy", "full"})


def _get_scheduler_mode() -> str:
    """Return SCHEDULER_MODE: light, heavy, or full (default)."""
    raw = os.environ.get("SCHEDULER_MODE", "full").strip().lower()
    if raw in _VALID_MODES:
        return raw
    logger.warning(
        "Invalid SCHEDULER_MODE=%r; using full. Valid: light, heavy, full.",
        raw,
    )
    return "full"


def _cluster_articles_guarded(config: dict[str, Any]) -> Any:
    """Run clustering only when no articles are pending extraction."""
    from app.clustering.service import StoryReport, run_cluster_and_embed

    pending = articles_db.get_pending_extraction_count()
    if pending > 0:
        logger.warning(
            "Skipping cluster job: %d articles still pending extraction",
            pending,
        )
        return StoryReport(
            articles_embedded=0,
            articles_clustered=0,
            stories_created=0,
        )
    return run_cluster_and_embed(config)


def _rewrite_articles_job(config: dict[str, Any]) -> Any:
    """Lazy import so light-only hosts never load LLM/rewrite stack."""
    from app.services.rewrite_service import run_rewrite_batch

    return run_rewrite_batch(config)


def _run_tracked_job(
    job_name: str,
    job_fn: Callable[[dict[str, Any]], Any],
    trigger: str = "scheduled",
) -> None:
    """Run a pipeline job with admin tracking. Wraps config load, execution, and result logging."""
    logger.info("Starting %s job", job_name)
    job_id = admin_db.insert_job_run(job_name, trigger=trigger)
    try:
        config = load_config()
        report = job_fn(config)
        admin_db.update_job_run(job_id, status="success", result=asdict(report))
        logger.info("%s job completed: %s", job_name, report)
    except Exception as e:
        admin_db.update_job_run(job_id, status="error", error_message=str(e))
        logger.exception("%s job failed", job_name)


def main() -> None:
    """Start the scheduler according to SCHEDULER_MODE."""
    if os.path.exists(".env"):
        from dotenv import load_dotenv

        load_dotenv()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    mode = _get_scheduler_mode()
    config = load_config()
    interval_min = config.get("schedule", {}).get("fetch_interval_minutes", 60)
    enrichment_cron = config.get("schedule", {}).get("enrichment_cron", "10 * * * *")
    cluster_cron = config.get("schedule", {}).get("cluster_cron", "5 * * * *")
    rewrite_cron = config.get("schedule", {}).get("rewrite_cron", "0 6 * * *")
    availability_interval = config.get("schedule", {}).get(
        "availability_check_interval_minutes", 10
    )

    scheduler = BlockingScheduler()

    if mode in ("light", "full"):
        scheduler.add_job(
            lambda: _run_tracked_job("fetch_feeds", fetch_all_due_feeds),
            trigger=IntervalTrigger(minutes=interval_min),
            id="fetch_feeds",
        )
        scheduler.add_job(
            lambda: _run_tracked_job("enrich_articles", enrich_all_articles),
            trigger=CronTrigger.from_crontab(enrichment_cron),
            id="enrich_articles",
        )
        scheduler.add_job(
            lambda: _run_tracked_job("check_source_availability", check_all_feeds_availability),
            trigger=IntervalTrigger(minutes=availability_interval),
            id="check_source_availability",
        )

    if mode in ("heavy", "full"):
        scheduler.add_job(
            lambda: _run_tracked_job("cluster_articles", _cluster_articles_guarded),
            trigger=CronTrigger.from_crontab(cluster_cron),
            id="cluster_articles",
        )
        scheduler.add_job(
            lambda: _run_tracked_job("rewrite_articles", _rewrite_articles_job),
            trigger=CronTrigger.from_crontab(rewrite_cron),
            id="rewrite_articles",
        )

    if mode == "light":
        logger.info(
            "Scheduler started (mode=light): fetch every %d min, enrichment=%s, "
            "availability every %d min",
            interval_min,
            enrichment_cron,
            availability_interval,
        )
    elif mode == "heavy":
        logger.info(
            "Scheduler started (mode=heavy): cluster=%s, rewrite=%s",
            cluster_cron,
            rewrite_cron,
        )
    else:
        logger.info(
            "Scheduler started (mode=full): fetch every %d min, enrichment=%s, cluster=%s, "
            "rewrite=%s, availability every %d min",
            interval_min,
            enrichment_cron,
            cluster_cron,
            rewrite_cron,
            availability_interval,
        )
    with contextlib.suppress(KeyboardInterrupt, SystemExit):
        scheduler.start()


if __name__ == "__main__":
    main()
