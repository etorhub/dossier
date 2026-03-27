"""Tests for app/scheduler.py — mode selection and job tracking helpers."""

from __future__ import annotations

import contextlib
import os
from dataclasses import dataclass
from unittest.mock import ANY, MagicMock, patch

import pytest

from app.scheduler import _get_scheduler_mode, _run_tracked_job

# ---------------------------------------------------------------------------
# _get_scheduler_mode
# ---------------------------------------------------------------------------


def test_get_scheduler_mode_defaults_to_full_when_unset() -> None:
    """Returns 'full' when SCHEDULER_MODE is not set."""
    env = {k: v for k, v in os.environ.items() if k != "SCHEDULER_MODE"}
    with patch.dict(os.environ, env, clear=True):
        assert _get_scheduler_mode() == "full"


@pytest.mark.parametrize("mode", ["full", "light", "heavy"])
def test_get_scheduler_mode_accepts_valid_values(mode: str) -> None:
    """Returns the mode as-is for valid values."""
    with patch.dict(os.environ, {"SCHEDULER_MODE": mode}):
        assert _get_scheduler_mode() == mode


def test_get_scheduler_mode_is_case_insensitive() -> None:
    """SCHEDULER_MODE=LIGHT is normalised to 'light'."""
    with patch.dict(os.environ, {"SCHEDULER_MODE": "LIGHT"}):
        assert _get_scheduler_mode() == "light"


def test_get_scheduler_mode_falls_back_to_full_for_invalid_value() -> None:
    """An unrecognised SCHEDULER_MODE value falls back to 'full'."""
    with patch.dict(os.environ, {"SCHEDULER_MODE": "banana"}):
        assert _get_scheduler_mode() == "full"


# ---------------------------------------------------------------------------
# _run_tracked_job
# ---------------------------------------------------------------------------


@dataclass
class _FakeReport:
    items: int
    errors: int


def test_run_tracked_job_calls_job_fn_with_config() -> None:
    """_run_tracked_job passes the loaded config to the job function."""
    config = {"schedule": {}}
    job_fn = MagicMock(return_value=_FakeReport(items=5, errors=0))

    with (
        patch("app.scheduler.load_config", return_value=config),
        patch("app.scheduler.admin_db.insert_job_run", return_value=1),
        patch("app.scheduler.admin_db.update_job_run"),
        patch("app.scheduler.job_run_file_logging") as mock_log_ctx,
        patch("app.scheduler.append_job_run_summary"),
    ):
        mock_log_ctx.return_value.__enter__ = MagicMock(return_value=(MagicMock(), "rel"))
        mock_log_ctx.return_value.__exit__ = MagicMock(return_value=False)
        _run_tracked_job("my_job", job_fn)

    job_fn.assert_called_once_with(config)


def test_run_tracked_job_marks_success_in_db() -> None:
    """_run_tracked_job calls update_job_run with status='success' on success."""
    job_fn = MagicMock(return_value={"count": 3})

    with (
        patch("app.scheduler.load_config", return_value={}),
        patch("app.scheduler.admin_db.insert_job_run", return_value=42),
        patch("app.scheduler.admin_db.update_job_run") as mock_update,
        patch("app.scheduler.job_run_file_logging") as mock_log_ctx,
        patch("app.scheduler.append_job_run_summary"),
    ):
        mock_log_ctx.return_value.__enter__ = MagicMock(return_value=(MagicMock(), "rel"))
        mock_log_ctx.return_value.__exit__ = MagicMock(return_value=False)
        _run_tracked_job("my_job", job_fn)

    mock_update.assert_called_once()
    call_kwargs = mock_update.call_args.kwargs
    assert call_kwargs["status"] == "success"
    assert mock_update.call_args.args[0] == 42


def test_run_tracked_job_marks_error_in_db_on_exception() -> None:
    """_run_tracked_job calls update_job_run with status='error' when the job raises."""
    job_fn = MagicMock(side_effect=RuntimeError("pipeline failure"))

    with (
        patch("app.scheduler.load_config", return_value={}),
        patch("app.scheduler.admin_db.insert_job_run", return_value=7),
        patch("app.scheduler.admin_db.update_job_run") as mock_update,
        patch("app.scheduler.job_run_file_logging") as mock_log_ctx,
        patch("app.scheduler.append_job_run_summary"),
    ):
        mock_log_ctx.return_value.__enter__ = MagicMock(return_value=(MagicMock(), "rel"))
        mock_log_ctx.return_value.__exit__ = MagicMock(return_value=False)
        _run_tracked_job("my_job", job_fn)  # must not raise

    mock_update.assert_called_once()
    call_kwargs = mock_update.call_args.kwargs
    assert call_kwargs["status"] == "error"
    assert "pipeline failure" in call_kwargs["error_message"]


def test_run_tracked_job_does_not_propagate_exception() -> None:
    """_run_tracked_job swallows exceptions raised by the job function."""
    job_fn = MagicMock(side_effect=ValueError("bad value"))

    with (
        patch("app.scheduler.load_config", return_value={}),
        patch("app.scheduler.admin_db.insert_job_run", return_value=1),
        patch("app.scheduler.admin_db.update_job_run"),
        patch("app.scheduler.job_run_file_logging") as mock_log_ctx,
        patch("app.scheduler.append_job_run_summary"),
    ):
        mock_log_ctx.return_value.__enter__ = MagicMock(return_value=(MagicMock(), "rel"))
        mock_log_ctx.return_value.__exit__ = MagicMock(return_value=False)
        # Should not raise
        _run_tracked_job("my_job", job_fn)


def test_run_tracked_job_serialises_dataclass_report() -> None:
    """_run_tracked_job converts a dataclass report to a dict for update_job_run."""
    report = _FakeReport(items=10, errors=2)
    job_fn = MagicMock(return_value=report)

    with (
        patch("app.scheduler.load_config", return_value={}),
        patch("app.scheduler.admin_db.insert_job_run", return_value=1),
        patch("app.scheduler.admin_db.update_job_run") as mock_update,
        patch("app.scheduler.job_run_file_logging") as mock_log_ctx,
        patch("app.scheduler.append_job_run_summary"),
    ):
        mock_log_ctx.return_value.__enter__ = MagicMock(return_value=(MagicMock(), "rel"))
        mock_log_ctx.return_value.__exit__ = MagicMock(return_value=False)
        _run_tracked_job("my_job", job_fn)

    result_dict = mock_update.call_args.kwargs["result"]
    assert result_dict == {"items": 10, "errors": 2}


def test_run_tracked_job_uses_trigger_parameter() -> None:
    """_run_tracked_job passes the trigger label to insert_job_run."""
    job_fn = MagicMock(return_value={})

    with (
        patch("app.scheduler.load_config", return_value={}),
        patch("app.scheduler.admin_db.insert_job_run", return_value=1) as mock_insert,
        patch("app.scheduler.admin_db.update_job_run"),
        patch("app.scheduler.job_run_file_logging") as mock_log_ctx,
        patch("app.scheduler.append_job_run_summary"),
    ):
        mock_log_ctx.return_value.__enter__ = MagicMock(return_value=(MagicMock(), "rel"))
        mock_log_ctx.return_value.__exit__ = MagicMock(return_value=False)
        _run_tracked_job("my_job", job_fn, trigger="manual")

    mock_insert.assert_called_once_with(
        "my_job",
        trigger="manual",
        origin_hostname=ANY,
        origin_ip=ANY,
        origin_mode=ANY,
    )


# ---------------------------------------------------------------------------
# main — job registration (smoke test, no actual scheduler start)
# ---------------------------------------------------------------------------


def test_main_registers_light_jobs_only_in_light_mode() -> None:
    """In 'light' mode, only the light-mode jobs are registered."""
    config: dict = {
        "schedule": {
            "fetch_interval_minutes": 60,
            "enrichment_cron": "10 * * * *",
            "cluster_cron": "5 * * * *",
            "rewrite_cron": "0 6 * * *",
            "highlight_cron": "15-59/30 * * * *",
            "availability_check_interval_minutes": 10,
        }
    }

    mock_scheduler = MagicMock()

    with (
        patch.dict(os.environ, {"SCHEDULER_MODE": "light"}),
        patch("app.scheduler.load_config", return_value=config),
        patch("app.scheduler.BlockingScheduler", return_value=mock_scheduler),
    ):
        from app.scheduler import main

        with contextlib.suppress(SystemExit):
            main()

    job_ids = [call.kwargs.get("id") for call in mock_scheduler.add_job.call_args_list]
    assert "fetch_feeds" in job_ids
    assert "enrich_articles" in job_ids
    assert "check_source_availability" in job_ids
    assert "cluster_articles" not in job_ids
    assert "rewrite_articles" not in job_ids


def test_main_registers_heavy_jobs_only_in_heavy_mode() -> None:
    """In 'heavy' mode, only the heavy-mode jobs are registered."""
    config: dict = {
        "schedule": {
            "fetch_interval_minutes": 60,
            "enrichment_cron": "10 * * * *",
            "cluster_cron": "5 * * * *",
            "rewrite_cron": "0 6 * * *",
            "highlight_cron": "15-59/30 * * * *",
            "availability_check_interval_minutes": 10,
        }
    }

    mock_scheduler = MagicMock()

    with (
        patch.dict(os.environ, {"SCHEDULER_MODE": "heavy"}),
        patch("app.scheduler.load_config", return_value=config),
        patch("app.scheduler.BlockingScheduler", return_value=mock_scheduler),
    ):
        from app.scheduler import main

        with contextlib.suppress(SystemExit):
            main()

    job_ids = [call.kwargs.get("id") for call in mock_scheduler.add_job.call_args_list]
    assert "fetch_feeds" not in job_ids
    assert "cluster_articles" in job_ids
    assert "rewrite_articles" in job_ids
    assert "highlight_stories" in job_ids
