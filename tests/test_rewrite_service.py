"""Tests for rewrite service."""

from unittest.mock import MagicMock, patch

import pytest

from app.services.rewrite_service import (
    RewriteReport,
    _parse_cluster_llm_response,
    _strip_markdown_bold,
    rewrite_story,
    run_rewrite_batch,
)


def test_parse_cluster_llm_response_happy() -> None:
    """_parse_cluster_llm_response extracts title, summary and full text."""
    text = """TITLE:
Power outage affects 500 homes.

SUMMARY:
First sentence. Second sentence. Third sentence.

FULL:
This is the full simplified article. Short sentences. Simple words."""
    title, summary, full = _parse_cluster_llm_response(text)
    assert "Power outage" in title
    assert "First sentence" in summary
    assert "This is the full simplified article" in full


def test_strip_markdown_bold() -> None:
    """_strip_markdown_bold removes ** from start and end of text."""
    assert _strip_markdown_bold("**Title here**") == "Title here"
    assert _strip_markdown_bold("** Power outage **") == "Power outage"
    assert _strip_markdown_bold("No asterisks") == "No asterisks"
    assert _strip_markdown_bold("**Only start") == "Only start"
    assert _strip_markdown_bold("Only end**") == "Only end"


def test_parse_cluster_llm_response_strips_markdown_bold() -> None:
    """_parse_cluster_llm_response strips ** from title, summary and full_text."""
    text = """TITLE:
**Power outage affects 500 homes.**

SUMMARY:
**First sentence. Second sentence. Third sentence.**

FULL:
**This is the full simplified article. Short sentences. Simple words.**"""
    title, summary, full = _parse_cluster_llm_response(text)
    assert title == "Power outage affects 500 homes."
    assert summary == "First sentence. Second sentence. Third sentence."
    assert full == "This is the full simplified article. Short sentences. Simple words."


def test_parse_cluster_llm_response_missing_title_raises() -> None:
    """_parse_cluster_llm_response raises ValueError when TITLE: missing."""
    text = "SUMMARY:\nS\nFULL:\nF"
    with pytest.raises(ValueError, match="missing TITLE"):
        _parse_cluster_llm_response(text)


def test_parse_cluster_llm_response_missing_full_raises() -> None:
    """_parse_cluster_llm_response raises ValueError when FULL: missing."""
    text = "TITLE:\nT\nSUMMARY:\nS"
    with pytest.raises(ValueError, match="TITLE:, SUMMARY:, or FULL:"):
        _parse_cluster_llm_response(text)


def test_parse_cluster_llm_response_empty_sections_raises() -> None:
    """_parse_cluster_llm_response raises ValueError when sections are empty."""
    text = "TITLE:\n\nSUMMARY:\n\nFULL:\n"
    with pytest.raises(ValueError, match="Empty"):
        _parse_cluster_llm_response(text)


def test_rewrite_cluster_empty_articles_stores_failed() -> None:
    """rewrite_cluster stores rewrite_failed=True when articles have no text."""
    with patch("app.services.rewrite_service.db_stories") as mock_db:
        articles = [{"id": "art1", "raw_text": "", "full_text": None}]
        config = {"rewriting": {"styles": [{"id": "neutral", "prompt": "rewrite_cluster_neutral"}]}}
        result = rewrite_story("story-1", articles, "neutral", "ca", config)
        assert result is False
        mock_db.insert_story_rewrite.assert_called_once_with(
            story_id="story-1",
            style="neutral",
            language="ca",
            title=None,
            summary=None,
            full_text=None,
            rewrite_failed=True,
            error_message="Articles have no full_text or raw_text",
        )


def test_rewrite_story_success_stores_rewrite() -> None:
    """rewrite_story stores title, summary and full_text on success."""
    with (
        patch("app.services.rewrite_service.db_stories") as mock_db,
        patch("app.services.rewrite_service.get_provider") as mock_get,
    ):
        mock_provider = MagicMock()
        mock_provider.complete.return_value = """TITLE:
Power outage in Barcelona.

SUMMARY:
One. Two. Three.

FULL:
Simplified article here."""
        mock_get.return_value = mock_provider

        articles = [
            {
                "id": "art1",
                "raw_text": "Original long article text.",
                "full_text": None,
            },
        ]
        config = {
            "processing": {"summary_sentences": 3},
            "rewriting": {"styles": [{"id": "neutral", "prompt": "rewrite_cluster_neutral"}]},
        }

        result = rewrite_story("story-1", articles, "neutral", "ca", config)
        assert result is True
        mock_db.insert_story_rewrite.assert_called_once_with(
            story_id="story-1",
            style="neutral",
            language="ca",
            title="Power outage in Barcelona.",
            summary="One. Two. Three.",
            full_text="Simplified article here.",
            rewrite_failed=False,
        )
        mock_provider.complete.assert_called_once()
        call_kwargs = mock_provider.complete.call_args[1]
        assert call_kwargs["max_tokens"] == 2000  # default when not in config


def test_rewrite_story_uses_config_max_tokens() -> None:
    """rewrite_story uses rewrite_max_tokens from config."""
    with (
        patch("app.services.rewrite_service.db_stories") as mock_db,
        patch("app.services.rewrite_service.get_provider") as mock_get,
    ):
        mock_provider = MagicMock()
        mock_provider.complete.return_value = """TITLE:
Title.

SUMMARY:
Summary.

FULL:
Full text."""
        mock_get.return_value = mock_provider

        articles = [{"id": "art1", "raw_text": "Text", "full_text": None}]
        config = {
            "processing": {"rewrite_max_tokens": 1500},
            "rewriting": {"styles": [{"id": "neutral", "prompt": "rewrite_cluster_neutral"}]},
        }

        rewrite_story("story-1", articles, "neutral", "ca", config)

        mock_provider.complete.assert_called_once()
        assert mock_provider.complete.call_args[1]["max_tokens"] == 1500


def test_rewrite_story_provider_error_stores_failed() -> None:
    """rewrite_story stores rewrite_failed=True when provider raises."""
    from app.llm.provider import LLMProviderError

    with (
        patch("app.services.rewrite_service.db_stories") as mock_db,
        patch("app.services.rewrite_service.get_provider") as mock_get,
    ):
        mock_provider = MagicMock()
        mock_provider.complete.side_effect = LLMProviderError("API down")
        mock_get.return_value = mock_provider

        articles = [{"id": "art1", "raw_text": "Some text", "full_text": None}]
        config = {"rewriting": {"styles": [{"id": "neutral", "prompt": "rewrite_cluster_neutral"}]}}

        result = rewrite_story("story-1", articles, "neutral", "ca", config)
        assert result is False
        mock_db.insert_story_rewrite.assert_called_once_with(
            story_id="story-1",
            style="neutral",
            language="ca",
            title=None,
            summary=None,
            full_text=None,
            rewrite_failed=True,
            error_message="API down",
        )


def test_run_rewrite_batch_unlimited_passes_no_sql_limit() -> None:
    """rewrite_batch_size 0 passes limit=None so all pending stories are selected."""
    with patch("app.services.rewrite_service.db_stories") as mock_stories:
        mock_stories.get_stories_needing_any_rewrite.return_value = []
        config = {
            "schedule": {"rewrite_batch_size": 0},
            "processing": {"cluster_window_hours": 24},
            "rewriting": {
                "base_language": "en",
                "styles": [{"id": "neutral"}, {"id": "simple"}],
                "languages": [{"id": "ca"}, {"id": "en"}],
            },
        }
        run_rewrite_batch(config)
        mock_stories.get_stories_needing_any_rewrite.assert_called_once()
        call_kw = mock_stories.get_stories_needing_any_rewrite.call_args.kwargs
        assert call_kw["limit"] is None


def test_run_rewrite_batch_empty_variants() -> None:
    """run_rewrite_batch returns zero counts when no stories need rewrite."""
    with patch("app.services.rewrite_service.db_stories") as mock_stories:
        mock_stories.get_stories_needing_any_rewrite.return_value = []
        config = {
            "schedule": {"rewrite_batch_size": 10},
            "processing": {"cluster_window_hours": 24},
            "rewriting": {
                "base_language": "en",
                "styles": [{"id": "neutral"}, {"id": "simple"}],
                "languages": [{"id": "ca"}, {"id": "es"}, {"id": "en"}],
            },
        }
        report = run_rewrite_batch(config)
        assert report == RewriteReport(
            variants_processed=6,
            stories_attempted=0,
            stories_succeeded=0,
            stories_failed=0,
        )


def test_run_rewrite_batch_counts() -> None:
    """run_rewrite_batch returns correct counts for mixed success/failure."""
    with (
        patch("app.services.rewrite_service.db_stories") as mock_stories,
        patch("app.services.rewrite_service._execute_cascading_rewrites") as mock_execute,
        patch("app.services.rewrite_service.get_provider") as mock_get,
    ):
        mock_get.return_value = MagicMock()
        mock_stories.get_stories_needing_any_rewrite.return_value = [
            {"story_id": "c1", "needs_rewrite": True},
            {"story_id": "c2", "needs_rewrite": True},
        ]
        mock_stories.get_articles_in_story.side_effect = [
            [{"id": "a1", "raw_text": "t1", "full_text": None}],
            [{"id": "a2", "raw_text": "t2", "full_text": None}],
        ]
        mock_execute.return_value = (5, 3)  # succeeded, failed

        config = {
            "schedule": {"rewrite_batch_size": 10},
            "processing": {"cluster_window_hours": 24},
            "rewriting": {
                "base_language": "en",
                "styles": [{"id": "neutral"}, {"id": "simple"}],
                "languages": [{"id": "ca"}, {"id": "es"}, {"id": "en"}],
            },
        }
        report = run_rewrite_batch(config)

        assert report.variants_processed == 6
        assert report.stories_attempted == 2
        assert report.stories_succeeded == 5
        assert report.stories_failed == 3


def test_run_rewrite_batch_calls_cascade() -> None:
    """run_rewrite_batch uses cascading rewrites (rewrite → simplify → translate)."""
    with (
        patch("app.services.rewrite_service.db_stories") as mock_stories,
        patch("app.services.rewrite_service.get_provider") as mock_get,
        patch("app.services.rewrite_service._execute_cascading_rewrites") as mock_execute,
    ):
        mock_get.return_value = MagicMock()
        mock_stories.get_stories_needing_any_rewrite.return_value = [
            {"story_id": "c1", "needs_rewrite": True},
        ]
        mock_stories.get_articles_in_story.return_value = [
            {"id": "a1", "raw_text": "t1", "full_text": None},
        ]
        mock_execute.return_value = (6, 0)  # all 6 variants succeeded

        config = {
            "schedule": {"rewrite_batch_size": 10},
            "processing": {"cluster_window_hours": 24},
            "rewriting": {
                "base_language": "en",
                "styles": [{"id": "neutral"}, {"id": "simple"}],
                "languages": [{"id": "ca"}, {"id": "es"}, {"id": "en"}],
            },
        }
        report = run_rewrite_batch(config)

        assert report.stories_attempted == 1
        assert report.stories_succeeded == 6
        mock_execute.assert_called_once()
        # Verify get_provider called with task for each step
        assert mock_get.call_count == 3
        tasks = [c[1]["task"] for c in mock_get.call_args_list if c[1].get("task")]
        assert "rewrite" in tasks
        assert "simplify" in tasks
        assert "translate" in tasks
