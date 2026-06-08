"""APScheduler entry point. Runs in the worker container.

Runs the full pipeline on a schedule: fetch feeds → enrich → check source
availability → cluster + embed → rewrite → highlight.
"""

from __future__ import annotations

import contextlib
import logging
import os
import socket
import time
from collections.abc import Callable
from dataclasses import asdict, is_dataclass
from typing import Any

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.config import load_config
from app.db import admin as admin_db
from app.extraction.extractor import enrich_all_articles
from app.feed.availability import check_all_feeds_availability
from app.feed.orchestrator import fetch_all_due_feeds
from app.job_run_logging import append_job_run_summary, job_run_file_logging

logger = logging.getLogger(__name__)

_ORIGIN_HOSTNAME: str = socket.gethostname()
try:
    _ORIGIN_IP: str | None = socket.gethostbyname(_ORIGIN_HOSTNAME)
except OSError:
    _ORIGIN_IP = None


def _cluster_articles_guarded(config: dict[str, Any]) -> Any:
    """Lazy import wrapper for the cluster+embed job."""
    from app.clustering.service import run_cluster_and_embed

    return run_cluster_and_embed(config)


def _rewrite_articles_job(config: dict[str, Any]) -> Any:
    """Lazy import so light-only hosts never load LLM/rewrite stack."""
    from app.services.rewrite_service import run_rewrite_batch

    report = run_rewrite_batch(config)

    digest_cfg = config.get("digest", {})
    if digest_cfg.get("send_push_notification") and report.stories_succeeded > 0:
        from app.services.push_service import send_digest_ready_notification

        try:
            send_digest_ready_notification(report.stories_succeeded)
        except Exception:
            logger.exception("Digest push notification failed (rewrite result still saved)")

    return report


def _highlight_articles_job(config: dict[str, Any]) -> Any:
    """Lazy import wrapper for the highlight job."""
    from app.services.highlight_service import run_highlight_batch

    return run_highlight_batch(config)


def _run_tracked_job(
    job_name: str,
    job_fn: Callable[[dict[str, Any]], Any],
    trigger: str = "scheduled",
) -> None:
    """Run a tracked pipeline job: config, job_fn, DB row, and per-run log file."""
    logger.info("Starting %s job", job_name)
    job_id = admin_db.insert_job_run(
        job_name,
        trigger=trigger,
        origin_hostname=_ORIGIN_HOSTNAME,
        origin_ip=_ORIGIN_IP,
        origin_mode="full",
    )
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
    """Start the scheduler and register all pipeline jobs."""
    if os.path.exists(".env"):
        from dotenv import load_dotenv

        load_dotenv()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    config = load_config()
    interval_min = config.get("schedule", {}).get("fetch_interval_minutes", 60)
    enrichment_cron = config.get("schedule", {}).get("enrichment_cron", "10 * * * *")
    cluster_cron = config.get("schedule", {}).get("cluster_cron", "5 * * * *")
    rewrite_cron = config.get("schedule", {}).get("rewrite_cron", "0 6 * * *")
    highlight_cron = config.get("schedule", {}).get("highlight_cron", "15-59/30 * * * *")
    availability_interval = config.get("schedule", {}).get(
        "availability_check_interval_minutes", 10
    )

    scheduler = BlockingScheduler()

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

    logger.info(
        "Scheduler started: fetch every %d min, enrichment=%s, "
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
