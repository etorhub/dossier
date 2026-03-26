"""Tests for clustering/feedback_agent.py."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.clustering.feedback_agent import (
    FeedbackReviewReport,
    _build_diagnostics,
    _build_story_block,
    _excerpt,
    _parse_llm_json,
    _validate_article_pair,
    _validate_source_pair,
    run_feedback_review,
)

# ---------------------------------------------------------------------------
# _excerpt
# ---------------------------------------------------------------------------


def test_excerpt_prefers_full_text_over_raw_text() -> None:
    """_excerpt returns full_text when available."""
    article = {"full_text": "Full content here.", "raw_text": "Raw content."}
    assert _excerpt(article) == "Full content here."


def test_excerpt_falls_back_to_raw_text() -> None:
    """_excerpt uses raw_text when full_text is absent."""
    article = {"full_text": "", "raw_text": "Raw content."}
    assert _excerpt(article) == "Raw content."


def test_excerpt_truncates_to_max_len() -> None:
    """_excerpt truncates to max_len characters."""
    article = {"full_text": "A" * 2000, "raw_text": ""}
    result = _excerpt(article, max_len=100)
    assert len(result) == 100


def test_excerpt_replaces_newlines() -> None:
    """_excerpt replaces newlines with spaces."""
    article = {"full_text": "line1\nline2\nline3", "raw_text": ""}
    assert "\n" not in _excerpt(article)


def test_excerpt_returns_placeholder_when_no_text() -> None:
    """_excerpt returns '(no text)' when both text fields are empty."""
    article = {"full_text": "", "raw_text": ""}
    assert _excerpt(article) == "(no text)"


# ---------------------------------------------------------------------------
# _parse_llm_json
# ---------------------------------------------------------------------------


def test_parse_llm_json_valid_json() -> None:
    """_parse_llm_json parses plain JSON objects."""
    result = _parse_llm_json('{"key": "value", "num": 42}')
    assert result == {"key": "value", "num": 42}


def test_parse_llm_json_json_in_code_fence() -> None:
    """_parse_llm_json extracts JSON from a ```json ... ``` block."""
    text = '```json\n{"rule_type": "article_pair"}\n```'
    result = _parse_llm_json(text)
    assert result == {"rule_type": "article_pair"}


def test_parse_llm_json_json_in_plain_fence() -> None:
    """_parse_llm_json extracts JSON from a ``` ... ``` block without language tag."""
    text = '```\n{"foo": "bar"}\n```'
    result = _parse_llm_json(text)
    assert result == {"foo": "bar"}


def test_parse_llm_json_json_embedded_in_prose() -> None:
    """_parse_llm_json extracts JSON embedded in surrounding prose."""
    text = 'Here is my analysis: {"confidence": "high"} and that is it.'
    result = _parse_llm_json(text)
    assert result == {"confidence": "high"}


def test_parse_llm_json_returns_none_for_garbage() -> None:
    """_parse_llm_json returns None when no valid JSON can be found."""
    assert _parse_llm_json("This is just plain text with no JSON.") is None


def test_parse_llm_json_returns_none_for_empty_string() -> None:
    """_parse_llm_json returns None for an empty string."""
    assert _parse_llm_json("") is None


# ---------------------------------------------------------------------------
# _build_story_block
# ---------------------------------------------------------------------------


def test_build_story_block_formats_articles() -> None:
    """_build_story_block includes id, source_id, title, and excerpt for each article."""
    articles = [
        {"id": "a1", "source_id": "src1", "title": "Article 1", "full_text": "Text one.", "raw_text": ""},
        {"id": "a2", "source_id": "src2", "title": "Article 2", "full_text": "Text two.", "raw_text": ""},
    ]
    block = _build_story_block(articles)
    assert "a1" in block
    assert "src1" in block
    assert "Article 1" in block
    assert "a2" in block


def test_build_story_block_returns_placeholder_for_empty_list() -> None:
    """_build_story_block returns a placeholder string when articles list is empty."""
    block = _build_story_block([])
    assert "no other articles" in block


# ---------------------------------------------------------------------------
# _build_diagnostics
# ---------------------------------------------------------------------------


def test_build_diagnostics_returns_placeholder_when_flagged_has_no_embedding() -> None:
    """_build_diagnostics returns a placeholder when the flagged article lacks an embedding."""
    flagged = {"id": "f1", "title": "Flagged"}  # no embedding
    others = [{"id": "o1", "title": "Other"}]
    result = _build_diagnostics(flagged, others)
    assert "no embedding" in result


def test_build_diagnostics_computes_similarity_when_embeddings_present() -> None:
    """_build_diagnostics shows a similarity score when both articles have embeddings."""
    vec = [1.0, 0.0, 0.0]
    flagged = {"id": "f1", "embedding": vec}
    others = [{"id": "o1", "embedding": vec}]

    with (
        patch("app.clustering.feedback_agent.embedding_from_article", side_effect=lambda a: a.get("embedding")),
        patch("app.clustering.feedback_agent.cosine_similarity", return_value=0.9999),
    ):
        result = _build_diagnostics(flagged, others)

    assert "o1" in result
    assert "0.9999" in result


# ---------------------------------------------------------------------------
# _validate_article_pair
# ---------------------------------------------------------------------------


def test_validate_article_pair_valid() -> None:
    """_validate_article_pair returns clean dict for valid article ids."""
    data = {"article_id_a": "a1", "article_id_b": "a2"}
    allowed = {"a1", "a2", "a3"}
    result = _validate_article_pair(data, "a1", allowed)
    assert result == {"article_id_a": "a1", "article_id_b": "a2"}


def test_validate_article_pair_rejects_ids_not_in_allowed_set() -> None:
    """_validate_article_pair returns None when ids are not in the allowed set."""
    data = {"article_id_a": "a1", "article_id_b": "unknown"}
    result = _validate_article_pair(data, "a1", {"a1", "a2"})
    assert result is None


def test_validate_article_pair_rejects_same_id_for_both() -> None:
    """_validate_article_pair returns None when both ids are identical."""
    data = {"article_id_a": "a1", "article_id_b": "a1"}
    result = _validate_article_pair(data, "a1", {"a1", "a2"})
    assert result is None


def test_validate_article_pair_rejects_non_string_ids() -> None:
    """_validate_article_pair returns None when ids are not strings."""
    data = {"article_id_a": 123, "article_id_b": "a2"}
    result = _validate_article_pair(data, "a1", {"a1", "a2"})
    assert result is None


# ---------------------------------------------------------------------------
# _validate_source_pair
# ---------------------------------------------------------------------------


def test_validate_source_pair_valid() -> None:
    """_validate_source_pair returns clean dict for valid source ids."""
    data = {"source_a": "src1", "source_b": "src2", "min_similarity": 0.95}
    result = _validate_source_pair(data, {"src1", "src2"})
    assert result is not None
    assert result["source_a"] == "src1"
    assert result["min_similarity"] == 0.95


def test_validate_source_pair_clamps_similarity_to_valid_range() -> None:
    """_validate_source_pair clamps min_similarity to [0.88, 0.98]."""
    data = {"source_a": "s1", "source_b": "s2", "min_similarity": 0.50}
    result = _validate_source_pair(data, {"s1", "s2"})
    assert result is not None
    assert result["min_similarity"] == 0.88

    data2 = {"source_a": "s1", "source_b": "s2", "min_similarity": 0.99}
    result2 = _validate_source_pair(data2, {"s1", "s2"})
    assert result2 is not None
    assert result2["min_similarity"] == 0.98


def test_validate_source_pair_rejects_unknown_sources() -> None:
    """_validate_source_pair returns None when source ids are not in the allowed set."""
    data = {"source_a": "src1", "source_b": "unknown"}
    result = _validate_source_pair(data, {"src1", "src2"})
    assert result is None


def test_validate_source_pair_defaults_similarity_on_invalid_value() -> None:
    """_validate_source_pair uses the default 0.93 when min_similarity is non-numeric."""
    data = {"source_a": "s1", "source_b": "s2", "min_similarity": "not-a-number"}
    result = _validate_source_pair(data, {"s1", "s2"})
    assert result is not None
    assert result["min_similarity"] == 0.93


# ---------------------------------------------------------------------------
# run_feedback_review
# ---------------------------------------------------------------------------


def test_run_feedback_review_returns_report_with_no_pending_rows() -> None:
    """run_feedback_review returns a FeedbackReviewReport with zeros when queue is empty."""
    with (
        patch("app.clustering.feedback_agent.admin_db.get_pending_clustering_feedback", return_value=[]),
        patch(
            "app.clustering.feedback_agent.apply_article_pair_rules_retroactively",
            return_value=0,
        ),
    ):
        report = run_feedback_review()

    assert isinstance(report, FeedbackReviewReport)
    assert report.rows_processed == 0
    assert report.rules_created == 0
    assert report.retroactive_removals == 0


def test_run_feedback_review_counts_processed_rows() -> None:
    """run_feedback_review counts each pending row as processed."""
    pending = [
        {"id": "f1", "article_id": "a1", "story_id": "s1"},
        {"id": "f2", "article_id": "a2", "story_id": "s2"},
    ]
    with (
        patch("app.clustering.feedback_agent.admin_db.get_pending_clustering_feedback", return_value=pending),
        patch("app.clustering.feedback_agent._process_one_pending", return_value=False),
        patch(
            "app.clustering.feedback_agent.apply_article_pair_rules_retroactively",
            return_value=0,
        ),
    ):
        report = run_feedback_review()

    assert report.rows_processed == 2


def test_run_feedback_review_counts_rules_created() -> None:
    """run_feedback_review increments rules_created when _process_one_pending returns True."""
    pending = [{"id": "f1", "article_id": "a1", "story_id": "s1"}]
    with (
        patch("app.clustering.feedback_agent.admin_db.get_pending_clustering_feedback", return_value=pending),
        patch("app.clustering.feedback_agent._process_one_pending", return_value=True),
        patch(
            "app.clustering.feedback_agent.apply_article_pair_rules_retroactively",
            return_value=0,
        ),
    ):
        report = run_feedback_review()

    assert report.rules_created == 1


def test_run_feedback_review_handles_exception_in_process_one_pending() -> None:
    """run_feedback_review catches exceptions from _process_one_pending and marks as failed."""
    pending = [{"id": "f1", "article_id": "a1", "story_id": "s1"}]
    with (
        patch("app.clustering.feedback_agent.admin_db.get_pending_clustering_feedback", return_value=pending),
        patch("app.clustering.feedback_agent._process_one_pending", side_effect=RuntimeError("boom")),
        patch("app.clustering.feedback_agent.admin_db.update_clustering_feedback_review") as mock_update,
        patch(
            "app.clustering.feedback_agent.apply_article_pair_rules_retroactively",
            return_value=0,
        ),
    ):
        report = run_feedback_review()

    # Exception must not propagate
    assert report.rows_processed == 1
    # Should have been finalized as failed
    mock_update.assert_called_once()
    assert mock_update.call_args.kwargs["status"] == "failed"


def test_run_feedback_review_includes_retroactive_removals() -> None:
    """run_feedback_review includes retroactive removal count in report."""
    with (
        patch("app.clustering.feedback_agent.admin_db.get_pending_clustering_feedback", return_value=[]),
        patch(
            "app.clustering.feedback_agent.apply_article_pair_rules_retroactively",
            return_value=3,
        ),
    ):
        report = run_feedback_review()

    assert report.retroactive_removals == 3
