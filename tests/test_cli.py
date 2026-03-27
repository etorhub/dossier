"""Tests for Flask CLI commands in app/cli.py."""

from __future__ import annotations

from unittest.mock import patch

from click.testing import CliRunner

from app.cli import make_admin, run_seed_sources, show_rewrite_failures

# ---------------------------------------------------------------------------
# run_seed_sources (the underlying function, not the CLI decorator)
# ---------------------------------------------------------------------------


def test_run_seed_sources_upserts_each_source() -> None:
    """run_seed_sources calls upsert_source for every entry in the config."""
    sources = [
        {
            "id": "src1",
            "domain": "example.com",
            "name": "Example",
            "homepage_url": "https://example.com",
            "country_code": "US",
            "languages": ["en"],
            "feeds": [{"url": "https://example.com/feed.xml", "type": "rss"}],
        },
        {
            "id": "src2",
            "domain": "other.com",
            "name": "Other",
            "homepage_url": "https://other.com",
            "country_code": "ES",
            "languages": ["ca"],
            "feeds": [],
        },
    ]

    with (
        patch("app.cli.load_sources", return_value=sources),
        patch("app.cli.sources_db.upsert_source") as mock_upsert,
        patch("app.cli.sources_db.delete_feeds_for_source"),
        patch("app.cli.sources_db.insert_feed"),
    ):
        run_seed_sources()

    assert mock_upsert.call_count == 2
    upserted_ids = [c.args[0]["id"] for c in mock_upsert.call_args_list]
    assert "src1" in upserted_ids
    assert "src2" in upserted_ids


def test_run_seed_sources_inserts_feeds_for_each_source() -> None:
    """run_seed_sources calls insert_feed for each feed in the source config."""
    sources = [
        {
            "id": "src1",
            "domain": "example.com",
            "name": "Example",
            "homepage_url": "https://example.com",
            "country_code": "US",
            "languages": ["en"],
            "feeds": [
                {"url": "https://example.com/feed1.xml"},
                {"url": "https://example.com/feed2.xml"},
            ],
        }
    ]

    with (
        patch("app.cli.load_sources", return_value=sources),
        patch("app.cli.sources_db.upsert_source"),
        patch("app.cli.sources_db.delete_feeds_for_source"),
        patch("app.cli.sources_db.insert_feed") as mock_insert,
    ):
        run_seed_sources()

    assert mock_insert.call_count == 2


def test_run_seed_sources_deletes_old_feeds_before_inserting() -> None:
    """run_seed_sources deletes existing feeds before inserting new ones."""
    sources = [
        {
            "id": "src1",
            "domain": "example.com",
            "name": "Example",
            "homepage_url": "https://example.com",
            "country_code": "US",
            "languages": ["en"],
            "feeds": [{"url": "https://example.com/feed.xml"}],
        }
    ]

    call_order: list[str] = []

    with (
        patch("app.cli.load_sources", return_value=sources),
        patch("app.cli.sources_db.upsert_source"),
        patch(
            "app.cli.sources_db.delete_feeds_for_source",
            side_effect=lambda sid: call_order.append("delete"),
        ),
        patch(
            "app.cli.sources_db.insert_feed",
            side_effect=lambda row: call_order.append("insert"),
        ),
    ):
        run_seed_sources()

    assert call_order == ["delete", "insert"]


def test_run_seed_sources_handles_empty_sources_list() -> None:
    """run_seed_sources does nothing when load_sources returns an empty list."""
    with (
        patch("app.cli.load_sources", return_value=[]),
        patch("app.cli.sources_db.upsert_source") as mock_upsert,
    ):
        run_seed_sources()

    mock_upsert.assert_not_called()


# ---------------------------------------------------------------------------
# seed-sources CLI command
# ---------------------------------------------------------------------------


def test_seed_sources_cli_command_runs_successfully() -> None:
    """The seed-sources Click command completes without error."""
    sources = [
        {
            "id": "s1",
            "domain": "example.com",
            "name": "Example",
            "homepage_url": "https://example.com",
            "country_code": "US",
            "languages": ["en"],
            "feeds": [],
        }
    ]
    runner = CliRunner()
    with (
        patch("app.cli.load_sources", return_value=sources),
        patch("app.cli.sources_db.upsert_source"),
        patch("app.cli.sources_db.delete_feeds_for_source"),
        patch("app.cli.sources_db.insert_feed"),
    ):
        result = runner.invoke(__import__("app.cli", fromlist=["seed_sources"]).seed_sources)
    assert result.exit_code == 0
    assert "Seeded 1 sources" in result.output


# ---------------------------------------------------------------------------
# make-admin CLI command
# ---------------------------------------------------------------------------


def test_make_admin_grants_admin_to_existing_user() -> None:
    """make-admin grants admin when the user exists."""
    user = {"id": 42, "email": "admin@example.com"}
    runner = CliRunner()

    with (
        patch("app.cli.db_users.get_user_by_email", return_value=user),
        patch("app.cli.db_users.set_admin") as mock_set,
    ):
        result = runner.invoke(make_admin, ["admin@example.com"])

    assert result.exit_code == 0
    assert "Granted admin" in result.output
    mock_set.assert_called_once_with(42, True)


def test_make_admin_exits_with_error_when_user_not_found() -> None:
    """make-admin exits with code 1 and an error message when the user is not found."""
    runner = CliRunner()

    with patch("app.cli.db_users.get_user_by_email", return_value=None):
        result = runner.invoke(make_admin, ["nobody@example.com"])

    assert result.exit_code == 1
    assert "not found" in result.output.lower()


# ---------------------------------------------------------------------------
# show-rewrite-failures CLI command
# ---------------------------------------------------------------------------


def test_show_rewrite_failures_outputs_message_when_no_failures() -> None:
    """show-rewrite-failures prints a 'no failures' message when the list is empty."""
    runner = CliRunner()

    with patch("app.cli.admin_db.get_recent_rewrite_failures", return_value=[]):
        result = runner.invoke(show_rewrite_failures, [])

    assert result.exit_code == 0
    assert "no rewrite failures" in result.output.lower()


def test_show_rewrite_failures_lists_failures() -> None:
    """show-rewrite-failures prints each failure entry."""
    from datetime import datetime

    failures = [
        {
            "cluster_id": "cluster-uuid-abc",
            "error_message": "LLM timeout",
            "created_at": datetime(2025, 1, 15, 10, 30),
        }
    ]
    runner = CliRunner()

    with patch("app.cli.admin_db.get_recent_rewrite_failures", return_value=failures):
        result = runner.invoke(show_rewrite_failures, ["--hours", "24"])

    assert result.exit_code == 0
    assert "cluster-" in result.output
    assert "LLM timeout" in result.output


def test_show_rewrite_failures_respects_hours_option() -> None:
    """show-rewrite-failures passes --hours to get_recent_rewrite_failures."""
    runner = CliRunner()

    with patch("app.cli.admin_db.get_recent_rewrite_failures", return_value=[]) as mock_get:
        runner.invoke(show_rewrite_failures, ["--hours", "48"])

    mock_get.assert_called_once_with(hours=48, limit=50)


def test_show_rewrite_failures_respects_limit_option() -> None:
    """show-rewrite-failures passes --limit to get_recent_rewrite_failures."""
    runner = CliRunner()

    with patch("app.cli.admin_db.get_recent_rewrite_failures", return_value=[]) as mock_get:
        runner.invoke(show_rewrite_failures, ["--limit", "10"])

    mock_get.assert_called_once_with(hours=24, limit=10)
