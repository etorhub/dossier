"""Per-job-run log files: capture logging + summary for ops dashboard."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from app.db import admin as admin_db

_LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
_LOG_DATEFMT = "%Y-%m-%d %H:%M:%S"


def job_run_log_relative_path(job_name: str, job_id: int) -> str:
    """Stable relative path stored in job_runs.log_path (POSIX)."""
    return f"{job_name}/{job_id}.log"


def job_run_log_root(config: dict[str, Any]) -> Path:
    """Absolute directory root for job run .log files."""
    raw = (config.get("paths") or {}).get("job_run_logs", "data/job_runs")
    p = Path(str(raw))
    if not p.is_absolute():
        p = Path.cwd() / p
    return p.resolve()


def resolve_job_run_log_file(config: dict[str, Any], log_rel: str) -> Path | None:
    """Resolve DB log_path under the configured root.

    Returns None if the path is unsafe or resolves outside the root.
    """
    if not log_rel or ".." in log_rel or log_rel.startswith(("/", "\\")):
        return None
    root = job_run_log_root(config)
    full = (root / log_rel).resolve()
    try:
        full.relative_to(root)
    except ValueError:
        return None
    return full


def append_job_run_summary(
    path: Path,
    *,
    status: str,
    duration_ms: int | None,
    result: dict[str, Any] | None,
    error_message: str | None,
) -> None:
    """Append structured summary to the end of the log file."""
    lines = [
        "",
        "=== Run summary ===",
        f"status: {status}",
    ]
    if duration_ms is not None:
        lines.append(f"duration_ms: {duration_ms}")
    if result is not None:
        lines.append("result:")
        lines.append(json.dumps(result, indent=2, default=str))
    if error_message:
        lines.append(f"error_message: {error_message}")
    lines.append("")
    with path.open("a", encoding="utf-8") as f:
        f.write("\n".join(lines))


@contextmanager
def job_run_file_logging(
    job_id: int,
    job_name: str,
    trigger: str,
    config: dict[str, Any],
) -> Iterator[tuple[Path, str]]:
    """Attach a file log handler; yield (absolute_path, relative_path_for_db)."""
    root = job_run_log_root(config)
    rel = job_run_log_relative_path(job_name, job_id)
    full = root / rel
    full.parent.mkdir(parents=True, exist_ok=True)

    with full.open("w", encoding="utf-8") as header_f:
        header_f.write(
            f"=== Job run id={job_id} job_name={job_name} trigger={trigger} ===\n"
            f"=== Log output (Python logging) ===\n\n"
        )

    handler = logging.FileHandler(full, mode="a", encoding="utf-8")
    stream = getattr(handler, "stream", None)
    if stream is not None and hasattr(stream, "reconfigure"):
        try:
            stream.reconfigure(line_buffering=True)
        except (OSError, ValueError, AttributeError):
            pass
    handler.setFormatter(logging.Formatter(_LOG_FORMAT, _LOG_DATEFMT))
    root_logger = logging.getLogger()
    root_logger.addHandler(handler)
    admin_db.set_job_run_log_path(job_id, rel)
    try:
        yield full, rel
    finally:
        root_logger.removeHandler(handler)
        handler.flush()
        handler.close()
