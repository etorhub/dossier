"""Tests for app/worker_cli.py CLI commands."""

from __future__ import annotations

from unittest.mock import patch

from click.testing import CliRunner

from app.worker_cli import worker_cli


def test_run_llm_stages_runs_three_stages_in_order() -> None:
    """run-llm-stages runs cluster → rewrite → highlight, each as a tracked job."""
    calls: list[str] = []

    def _record(job_name: str, _fn: object, trigger: str = "scheduled") -> None:
        calls.append(job_name)

    with (
        patch("app.scheduler._run_tracked_job", side_effect=_record) as mock_tracked,
        patch("app.clustering.service.run_cluster_and_embed"),
        patch("app.services.rewrite_service.run_rewrite_batch"),
        patch("app.services.highlight_service.run_highlight_batch"),
    ):
        result = CliRunner().invoke(worker_cli, ["run-llm-stages"])

    assert result.exit_code == 0, result.output
    assert calls == ["cluster_articles", "rewrite_articles", "highlight_stories"]
    # Each stage runs with trigger="manual" so ops shows it as an off-host run.
    for call in mock_tracked.call_args_list:
        assert call.kwargs.get("trigger") == "manual"
