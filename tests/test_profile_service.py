"""Tests for profile_service."""

from app.services.profile_service import (
    get_style_options,
    normalize_preferred_style,
    regeneration_needed,
)


def test_regeneration_needed_when_language_changes() -> None:
    """regeneration_needed returns True when language changes."""
    old = {"language": "ca", "topic_ids": ["t1"]}
    new_form = {"language": "es"}
    assert regeneration_needed(old, new_form, ["t1"]) is True


def test_regeneration_needed_when_source_ids_change() -> None:
    """regeneration_needed returns True when source_ids change."""
    old = {"language": "ca", "topic_ids": ["t1"]}
    new_form = {"language": "ca"}
    assert regeneration_needed(old, new_form, ["t1", "t2"]) is True


def test_regeneration_needed_when_topic_ids_change() -> None:
    """regeneration_needed returns True when topic_ids change."""
    old = {"language": "ca", "topic_ids": ["t1"]}
    new_form = {"language": "ca"}
    assert regeneration_needed(old, new_form, ["t1", "t2"]) is True


def test_get_style_options_empty_config() -> None:
    """Empty rewriting.styles falls back to a single neutral option."""
    assert get_style_options({}) == [("neutral", "Neutral")]


def test_normalize_preferred_style_rejects_unknown_id() -> None:
    """Unknown style id is replaced with default_style from config."""
    cfg = {
        "rewriting": {
            "styles": [{"id": "neutral", "label": "Neutral"}],
            "default_style": "neutral",
        }
    }
    assert normalize_preferred_style("simple", cfg) == "neutral"


def test_regeneration_needed_when_preferred_style_changes() -> None:
    """regeneration_needed returns True when preferred_style changes."""
    old = {
        "language": "ca",
        "preferred_style": "neutral",
        "topic_ids": ["t1"],
    }
    new_form = {
        "language": "ca",
        "preferred_style": "simple",
    }
    assert regeneration_needed(old, new_form, ["t1"]) is True


def test_regeneration_needed_when_location_changes() -> None:
    """regeneration_needed returns True when location changes."""
    old = {
        "location": "Barcelona",
        "language": "ca",
        "topic_ids": ["t1"],
    }
    new_form = {"location": "Madrid", "language": "ca"}
    assert regeneration_needed(old, new_form, ["t1"]) is True


def test_regeneration_not_needed_when_only_high_contrast_changes() -> None:
    """regeneration_needed returns False when only high_contrast changes."""
    old = {
        "language": "ca",
        "preferred_style": "simple",
        "topic_ids": ["t1"],
    }
    new_form = {
        "language": "ca",
        "preferred_style": "simple",
        "high_contrast": True,
    }
    assert regeneration_needed(old, new_form, ["t1"]) is False


def test_regeneration_not_needed_when_nothing_changes() -> None:
    """regeneration_needed returns False when no regeneration field changes."""
    old = {"language": "ca", "topic_ids": ["t1"]}
    new_form = {"language": "ca"}
    assert regeneration_needed(old, new_form, ["t1"]) is False


def test_regeneration_not_needed_when_source_order_differs() -> None:
    """regeneration_needed returns False when source_ids same but order differs."""
    old = {"language": "ca", "topic_ids": ["t1"]}
    new_form = {"language": "ca"}
    assert regeneration_needed(old, new_form, ["t1"]) is False
