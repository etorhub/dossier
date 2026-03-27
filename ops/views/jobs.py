"""Pipeline jobs view."""

from flask import Blueprint, Response, render_template, request

from app.db import admin as admin_db

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
