"""Tests for clustering/retroactive_rules.py."""

from __future__ import annotations

from unittest.mock import call, patch

import pytest

from app.clustering.retroactive_rules import apply_article_pair_rules_retroactively


def _make_rule(
    rule_type: str = "article_pair",
    a: str = "art-a",
    b: str = "art-b",
    feedback_id: str | None = None,
) -> dict:
    return {
        "rule_type": rule_type,
        "rule_data": {"article_id_a": a, "article_id_b": b},
        "feedback_id": feedback_id,
    }


# ---------------------------------------------------------------------------
# apply_article_pair_rules_retroactively
# ---------------------------------------------------------------------------


def test_returns_zero_when_no_rules() -> None:
    """Returns 0 when there are no active exclusion rules."""
    with patch("app.clustering.retroactive_rules.admin_db.get_active_exclusion_rules", return_value=[]):
        result = apply_article_pair_rules_retroactively()
    assert result == 0


def test_skips_non_article_pair_rules() -> None:
    """Rules with rule_type != 'article_pair' are ignored."""
    rules = [
        {"rule_type": "source_pair", "rule_data": {"source_a": "s1", "source_b": "s2"}},
        {"rule_type": "keyword", "rule_data": {"keyword": "foo"}},
    ]
    with (
        patch("app.clustering.retroactive_rules.admin_db.get_active_exclusion_rules", return_value=rules),
        patch("app.clustering.retroactive_rules.stories_db.get_story_ids_for_articles") as mock_stories,
    ):
        result = apply_article_pair_rules_retroactively()

    assert result == 0
    mock_stories.assert_not_called()


def test_skips_rule_when_articles_are_in_different_stories() -> None:
    """No removal when article_a and article_b are in different stories."""
    rule = _make_rule(a="a1", b="b1")
    smap = {"a1": "story-1", "b1": "story-2"}  # different stories
    with (
        patch("app.clustering.retroactive_rules.admin_db.get_active_exclusion_rules", return_value=[rule]),
        patch("app.clustering.retroactive_rules.stories_db.get_story_ids_for_articles", return_value=smap),
    ):
        result = apply_article_pair_rules_retroactively()

    assert result == 0


def test_skips_rule_when_article_not_in_any_story() -> None:
    """No removal when one of the articles is not in any story."""
    rule = _make_rule(a="a1", b="b1")
    smap = {"a1": "story-1"}  # b1 missing
    with (
        patch("app.clustering.retroactive_rules.admin_db.get_active_exclusion_rules", return_value=[rule]),
        patch("app.clustering.retroactive_rules.stories_db.get_story_ids_for_articles", return_value=smap),
    ):
        result = apply_article_pair_rules_retroactively()

    assert result == 0


def test_removes_article_b_by_default() -> None:
    """When both articles are in the same story and there is no feedback_id, removes article_b."""
    rule = _make_rule(a="art-a", b="art-b", feedback_id=None)
    smap = {"art-a": "story-1", "art-b": "story-1"}

    with (
        patch("app.clustering.retroactive_rules.admin_db.get_active_exclusion_rules", return_value=[rule]),
        patch("app.clustering.retroactive_rules.stories_db.get_story_ids_for_articles", return_value=smap),
        patch("app.clustering.retroactive_rules.stories_db.remove_article_from_story", return_value=True) as mock_remove,
        patch("app.clustering.retroactive_rules.recompute_story_centroid"),
        patch("app.clustering.retroactive_rules.stories_db.set_story_needs_rewrite"),
    ):
        result = apply_article_pair_rules_retroactively()

    assert result == 1
    mock_remove.assert_called_once_with("story-1", "art-b")


def test_removes_flagged_article_when_feedback_id_present() -> None:
    """When feedback_id is set, removes the article flagged in that feedback row."""
    rule = _make_rule(a="art-a", b="art-b", feedback_id="fb-1")
    smap = {"art-a": "story-1", "art-b": "story-1"}

    with (
        patch("app.clustering.retroactive_rules.admin_db.get_active_exclusion_rules", return_value=[rule]),
        patch("app.clustering.retroactive_rules.stories_db.get_story_ids_for_articles", return_value=smap),
        # Flagged article in the feedback row is art-a
        patch(
            "app.clustering.retroactive_rules.admin_db.get_clustering_feedback_flagged_article_id",
            return_value="art-a",
        ),
        patch("app.clustering.retroactive_rules.stories_db.remove_article_from_story", return_value=True) as mock_remove,
        patch("app.clustering.retroactive_rules.recompute_story_centroid"),
        patch("app.clustering.retroactive_rules.stories_db.set_story_needs_rewrite"),
    ):
        result = apply_article_pair_rules_retroactively()

    assert result == 1
    mock_remove.assert_called_once_with("story-1", "art-a")


def test_falls_back_to_article_b_when_flagged_article_not_in_pair() -> None:
    """Falls back to removing art-b when the flagged article is not in the pair."""
    rule = _make_rule(a="art-a", b="art-b", feedback_id="fb-1")
    smap = {"art-a": "story-1", "art-b": "story-1"}

    with (
        patch("app.clustering.retroactive_rules.admin_db.get_active_exclusion_rules", return_value=[rule]),
        patch("app.clustering.retroactive_rules.stories_db.get_story_ids_for_articles", return_value=smap),
        patch(
            "app.clustering.retroactive_rules.admin_db.get_clustering_feedback_flagged_article_id",
            return_value="unrelated-article",
        ),
        patch("app.clustering.retroactive_rules.stories_db.remove_article_from_story", return_value=True) as mock_remove,
        patch("app.clustering.retroactive_rules.recompute_story_centroid"),
        patch("app.clustering.retroactive_rules.stories_db.set_story_needs_rewrite"),
    ):
        result = apply_article_pair_rules_retroactively()

    assert result == 1
    mock_remove.assert_called_once_with("story-1", "art-b")


def test_recomputes_centroid_and_marks_needs_rewrite_after_removal() -> None:
    """After a successful removal, centroid is recomputed and story is marked needs_rewrite."""
    rule = _make_rule(a="art-a", b="art-b")
    smap = {"art-a": "story-1", "art-b": "story-1"}

    with (
        patch("app.clustering.retroactive_rules.admin_db.get_active_exclusion_rules", return_value=[rule]),
        patch("app.clustering.retroactive_rules.stories_db.get_story_ids_for_articles", return_value=smap),
        patch("app.clustering.retroactive_rules.stories_db.remove_article_from_story", return_value=True),
        patch("app.clustering.retroactive_rules.recompute_story_centroid") as mock_centroid,
        patch("app.clustering.retroactive_rules.stories_db.set_story_needs_rewrite") as mock_rewrite,
    ):
        apply_article_pair_rules_retroactively()

    mock_centroid.assert_called_once_with("story-1")
    mock_rewrite.assert_called_once_with("story-1", True)


def test_does_not_count_failed_removal() -> None:
    """Does not count removal when remove_article_from_story returns False."""
    rule = _make_rule(a="art-a", b="art-b")
    smap = {"art-a": "story-1", "art-b": "story-1"}

    with (
        patch("app.clustering.retroactive_rules.admin_db.get_active_exclusion_rules", return_value=[rule]),
        patch("app.clustering.retroactive_rules.stories_db.get_story_ids_for_articles", return_value=smap),
        patch("app.clustering.retroactive_rules.stories_db.remove_article_from_story", return_value=False),
        patch("app.clustering.retroactive_rules.recompute_story_centroid"),
        patch("app.clustering.retroactive_rules.stories_db.set_story_needs_rewrite"),
    ):
        result = apply_article_pair_rules_retroactively()

    assert result == 0


def test_processes_multiple_rules() -> None:
    """Processes each matching rule independently."""
    rules = [
        _make_rule(a="a1", b="b1"),
        _make_rule(a="a2", b="b2"),
    ]
    smap_calls = [
        {"a1": "story-1", "b1": "story-1"},
        {"a2": "story-2", "b2": "story-2"},
    ]

    call_count = 0

    def fake_get_story_ids(ids: list) -> dict:
        nonlocal call_count
        result = smap_calls[call_count]
        call_count += 1
        return result

    with (
        patch("app.clustering.retroactive_rules.admin_db.get_active_exclusion_rules", return_value=rules),
        patch("app.clustering.retroactive_rules.stories_db.get_story_ids_for_articles", side_effect=fake_get_story_ids),
        patch("app.clustering.retroactive_rules.stories_db.remove_article_from_story", return_value=True),
        patch("app.clustering.retroactive_rules.recompute_story_centroid"),
        patch("app.clustering.retroactive_rules.stories_db.set_story_needs_rewrite"),
    ):
        result = apply_article_pair_rules_retroactively()

    assert result == 2
