"""Unit tests for topic-gate and embedding-text helpers in clustering service."""

import pytest

from app.clustering.service import _topics_compatible, _text_to_embed


# --- _topics_compatible ---

def _t(topics_a: list[str], topics_b: list[str], known: dict | None = None) -> bool:
    """Helper: build minimal source_topics and call _topics_compatible."""
    source_topics = {"src_a": frozenset(topics_a), "src_b": frozenset(topics_b)}
    if known:
        source_topics.update({k: frozenset(v) for k, v in known.items()})
    return _topics_compatible("src_a", "src_b", source_topics)


def test_sports_vs_politics_blocked() -> None:
    assert _t(["sports"], ["politics", "society"]) is False


def test_sports_vs_international_blocked() -> None:
    assert _t(["sports"], ["international"]) is False


def test_same_domain_allowed() -> None:
    assert _t(["sports"], ["sports"]) is True


def test_overlapping_domains_allowed() -> None:
    assert _t(["politics", "society"], ["politics", "economy"]) is True


def test_general_source_always_compatible_with_sports() -> None:
    assert _t(["general"], ["sports"]) is True


def test_general_source_always_compatible_with_politics() -> None:
    assert _t(["politics", "society"], ["general", "politics"]) is True


def test_unknown_source_permissive() -> None:
    """Sources not in index default to compatible."""
    source_topics: dict[str, frozenset[str]] = {"src_a": frozenset(["sports"])}
    assert _topics_compatible("src_a", "unknown_src", source_topics) is True


def test_both_unknown_permissive() -> None:
    assert _topics_compatible("x", "y", {}) is True


# --- _text_to_embed ---

def _make_article(
    title: str = "Title",
    full_text: str = "",
    raw_text: str = "",
    categories: list | None = None,
    source_topics: list | None = None,
) -> dict:
    return {
        "title": title,
        "full_text": full_text,
        "raw_text": raw_text,
        "categories": categories or [],
        "_source_topics": source_topics or [],
    }


def test_text_to_embed_no_context_is_plain() -> None:
    art = _make_article(title="Headline", full_text="Body text.")
    result = _text_to_embed(art)
    assert result == "Headline Body text."


def test_text_to_embed_prepends_source_topics() -> None:
    art = _make_article(title="Match result", source_topics=["sports"])
    result = _text_to_embed(art)
    assert result.startswith("topics: sports.")


def test_text_to_embed_prepends_categories() -> None:
    art = _make_article(title="Match result", categories=["Football", "La Liga"])
    result = _text_to_embed(art)
    assert "categories: Football, La Liga" in result


def test_text_to_embed_topics_and_categories() -> None:
    art = _make_article(
        title="Transfer news",
        source_topics=["sports"],
        categories=["Football"],
    )
    result = _text_to_embed(art)
    assert result.startswith("topics: sports. categories: Football.")


def test_text_to_embed_content_truncated_at_2000() -> None:
    art = _make_article(title="T", full_text="x" * 3000)
    result = _text_to_embed(art)
    # "T" (1) + " " (1) + "x" * 2000 = 2002 chars; no prefix because no topics/categories
    assert len(result) == 2002


def test_text_to_embed_falls_back_to_raw_text() -> None:
    art = _make_article(title="T", raw_text="raw content")
    result = _text_to_embed(art)
    assert "raw content" in result


def test_text_to_embed_empty_categories_ignored() -> None:
    art = _make_article(title="T", categories=["", "  ", None])
    result = _text_to_embed(art)
    assert "categories" not in result
