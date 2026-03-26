"""Embedding queue snapshot for CLI / shell dashboards (ops visibility)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

from app.config import load_config
from app.db import admin as admin_db
from app.db import articles as db_articles


def _serialize_dt(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat()


def _cluster_result_summary(result: Any) -> dict[str, Any] | None:
    if not result:
        return None
    if isinstance(result, str):
        try:
            result = json.loads(result)
        except json.JSONDecodeError:
            return None
    if not isinstance(result, dict):
        return None
    return {
        "articles_embedded": result.get("articles_embedded"),
        "articles_clustered": result.get("articles_clustered"),
        "stories_created": result.get("stories_created"),
    }


def build_embedding_status(config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return a JSON-serializable snapshot aligned with run_cluster_and_embed window/batch."""
    cfg = config or load_config()
    processing = cfg.get("processing", {})
    window_hours = processing.get("cluster_window_hours", 24)
    embed_batch = int(processing.get("embed_batch_size") or 0)

    since: datetime | None = (
        datetime.now(UTC) - timedelta(hours=window_hours) if window_hours else None
    )

    pending_window = db_articles.count_recent_articles_without_embedding(since)
    pending_total = db_articles.count_recent_articles_without_embedding(None)
    embedded_window = db_articles.count_recent_articles_with_valid_embedding(since)
    articles_in_window = db_articles.count_articles_published_since(since)

    pct: float | None = (
        100.0 * embedded_window / articles_in_window if articles_in_window > 0 else None
    )

    unfinished = admin_db.get_unfinished_job_run("cluster_articles")
    runs = admin_db.get_recent_job_runs(limit=20, job_name="cluster_articles")
    last_finished = next((r for r in runs if r.get("finished_at")), None)

    last_job: dict[str, Any] | None = None
    if last_finished:
        res_raw = last_finished.get("result")
        last_job = {
            "id": last_finished.get("id"),
            "status": last_finished.get("status"),
            "trigger": last_finished.get("trigger"),
            "started_at": _serialize_dt(last_finished.get("started_at")),
            "finished_at": _serialize_dt(last_finished.get("finished_at")),
            "duration_ms": last_finished.get("duration_ms"),
            "result": _cluster_result_summary(res_raw),
            "error_message": last_finished.get("error_message"),
        }

    return {
        "cluster_window_hours": window_hours,
        "embed_batch_size": embed_batch,
        "window_since_utc": _serialize_dt(since),
        "articles_in_window": articles_in_window,
        "embedded_in_window": embedded_window,
        "pending_embed_in_window": pending_window,
        "pending_embed_total": pending_total,
        "pct_embedded_in_window": round(pct, 1) if pct is not None else None,
        "cluster_job_running": unfinished is not None,
        "running_job_started_at": _serialize_dt(unfinished.get("started_at"))
        if unfinished
        else None,
        "last_cluster_job": last_job,
    }
