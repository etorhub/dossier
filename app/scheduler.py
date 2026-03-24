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
import time
from collections.abc import Callable
from dataclasses import asdict, is_dataclass
from typing import Any

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.config import load_config
from app.db import admin as admin_db
from app.db import articles as articles_db
from app.extraction.extractor import enrich_all_articles
from app.feed.availability import check_all_feeds_availability
from app.feed.orchestrator import fetch_all_due_feeds
from app.job_run_logging import append_job_run_summary, job_run_file_logging

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


def _highlight_articles_job(config: dict[str, Any]) -> Any:
    """Lazy import so light-only hosts never load LLM/highlight stack."""
    from app.services.highlight_service import run_highlight_batch

    return run_highlight_batch(config)


def _run_tracked_job(
    job_name: str,
    job_fn: Callable[[dict[str, Any]], Any],
    trigger: str = "scheduled",
) -> None:
    """Run a tracked pipeline job: config, job_fn, DB row, and per-run log file."""
    logger.info("Starting %s job", job_name)
    job_id = admin_db.insert_job_run(job_name, trigger=trigger)
    config = load_config()
    t0 = time.perf_counter()
    with job_run_file_logging(
        job_id,
        job_name,
        trigger,
        config,
    ) as (log_file, _log_rel):
        try:
            report = job_fn(config)
            if is_dataclass(report) and not isinstance(report, type):
                result_dict = asdict(report)
            elif isinstance(report, dict):
                result_dict = report
            else:
                result_dict = {"value": repr(report)}
            duration_ms = int((time.perf_counter() - t0) * 1000)
            admin_db.update_job_run(job_id, status="success", result=result_dict)
            logger.info("%s job completed: %s", job_name, report)
            append_job_run_summary(
                log_file,
                status="success",
                duration_ms=duration_ms,
                result=result_dict,
                error_message=None,
            )
        except Exception as e:
            duration_ms = int((time.perf_counter() - t0) * 1000)
            logger.exception("%s job failed", job_name)
            append_job_run_summary(
                log_file,
                status="error",
                duration_ms=duration_ms,
                result=None,
                error_message=str(e),
            )
            admin_db.update_job_run(job_id, status="error", error_message=str(e))


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
    highlight_cron = config.get("schedule", {}).get("highlight_cron", "30 6 * * *")
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
            lambda: _run_tracked_job(
                "check_source_availability",
                check_all_feeds_availability,
            ),
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
        scheduler.add_job(
            lambda: _run_tracked_job("highlight_stories", _highlight_articles_job),
            trigger=CronTrigger.from_crontab(highlight_cron),
            id="highlight_stories",
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
            "Scheduler started (mode=heavy): cluster=%s, rewrite=%s, highlight=%s",
            cluster_cron,
            rewrite_cron,
            highlight_cron,
        )
    else:
        logger.info(
            "Scheduler started (mode=full): fetch every %d min, enrichment=%s, "
            "cluster=%s, rewrite=%s, highlight=%s, availability every %d min",
            interval_min,
            enrichment_cron,
            cluster_cron,
            rewrite_cron,
            highlight_cron,
            availability_interval,
        )
    with contextlib.suppress(KeyboardInterrupt, SystemExit):
        scheduler.start()


if __name__ == "__main__":
    main()
