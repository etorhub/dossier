"""Pipeline jobs view."""

from flask import Blueprint, Response, render_template, request

from app.config import load_config
from app.db import admin as admin_db
from app.job_run_logging import resolve_job_run_log_file

jobs_bp = Blueprint("jobs", __name__)


@jobs_bp.route("/")
def index() -> Response:
    """Jobs list with pagination and filters."""
    page = max(1, request.args.get("page", 1, type=int))
    per_page = min(100, max(10, request.args.get("per_page", 50, type=int)))
    job_name = request.args.get("job_name") or None
    status = request.args.get("status") or None

    total = admin_db.get_job_runs_count(job_name=job_name, status=status)
    offset = (page - 1) * per_page
    job_runs = admin_db.get_job_runs_paginated(
        limit=per_page,
        offset=offset,
        job_name=job_name,
        status=status,
    )

    return render_template(
        "ops/jobs.html",
        job_runs=job_runs,
        total=total,
        page=page,
        per_page=per_page,
        job_name=job_name,
        status=status,
    )


@jobs_bp.route("/<int:job_id>/log")
def job_run_log(job_id: int) -> Response:
    """Plain-text job run log (logging output + summary footer)."""
    row = admin_db.get_job_run_by_id(job_id)
    if not row:
        return (
            render_template(
                "ops/job_run_log.html",
                job=None,
                log_body="",
                missing=True,
                reason="Job run not found.",
            ),
            404,
        )

    log_rel = row.get("log_path")
    if not log_rel:
        return render_template(
            "ops/job_run_log.html",
            job=row,
            log_body="",
            missing=True,
            reason="",
        )

    cfg = load_config()
    path = resolve_job_run_log_file(cfg, str(log_rel))
    if path is None or not path.is_file():
        return render_template(
            "ops/job_run_log.html",
            job=row,
            log_body="",
            missing=True,
            reason=(
                "Log file not found on disk "
                "(check paths.job_run_logs and worker/ops volume)."
            ),
        )

    body = path.read_text(encoding="utf-8", errors="replace")
    return render_template(
        "ops/job_run_log.html",
        job=row,
        log_body=body,
        missing=False,
    )


@jobs_bp.route("/partials/table")
def table_partial() -> Response:
    """HTMX partial: job runs table."""
    page = max(1, request.args.get("page", 1, type=int))
    per_page = min(100, max(10, request.args.get("per_page", 50, type=int)))
    job_name = request.args.get("job_name") or None
    status = request.args.get("status") or None

    total = admin_db.get_job_runs_count(job_name=job_name, status=status)
    offset = (page - 1) * per_page
    job_runs = admin_db.get_job_runs_paginated(
        limit=per_page,
        offset=offset,
        job_name=job_name,
        status=status,
    )

    return render_template(
        "ops/partials/jobs_table.html",
        job_runs=job_runs,
        total=total,
        page=page,
        per_page=per_page,
        job_name=job_name,
        status=status,
    )
