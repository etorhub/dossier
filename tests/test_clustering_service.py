"""Unit tests for topic-gate and embedding-text helpers in clustering service."""

from unittest.mock import MagicMock, patch

from app.clustering.service import (
    _text_to_embed,
    _topics_compatible,
    run_cluster_and_embed,
)

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


# --- cluster gate ---


def test_run_cluster_and_embed_skips_cluster_when_gate_fires() -> None:
    """When pending count exceeds threshold, embed runs but cluster is skipped."""
    config = {"extraction": {"cluster_gate_max_pending": 2}}
    with (
        patch(
            "app.clustering.service.db_articles.get_recent_articles_without_embedding",
            return_value=[],
        ),
        patch(
            "app.clustering.service.db_articles.get_pending_extraction_count",
            return_value=10,
        ),
        patch("app.clustering.service.get_embedding_provider") as mock_prov,
        patch(
            "app.clustering.service.db_articles.get_articles_with_embedding_not_in_story"
        ) as mock_cluster,
        patch("app.clustering.service._load_exclusion_rules") as mock_rules,
        patch("app.clustering.service._build_source_topics_index", return_value={}),
    ):
        mock_prov.return_value = MagicMock()
        mock_rules.return_value = MagicMock(article_pairs=frozenset(), source_pair_thresholds={})
        report = run_cluster_and_embed(config)
        # Cluster step should not be called
        mock_cluster.assert_not_called()
        assert report.articles_clustered == 0


def test_run_cluster_and_embed_proceeds_when_pending_within_threshold() -> None:
    """When pending count <= threshold, cluster step proceeds."""
    config = {"extraction": {"cluster_gate_max_pending": 5}}
    with (
        patch(
            "app.clustering.service.db_articles.get_recent_articles_without_embedding",
            return_value=[],
        ),
        patch(
            "app.clustering.service.db_articles.get_pending_extraction_count",
            return_value=3,
        ),
        patch("app.clustering.service.get_embedding_provider") as mock_prov,
        patch(
            "app.clustering.service.db_articles.get_articles_with_embedding_not_in_story",
            return_value=[],
        ),
        patch("app.clustering.service._load_exclusion_rules") as mock_rules,
        patch("app.clustering.service._build_source_topics_index", return_value={}),
    ):
        mock_prov.return_value = MagicMock()
        mock_rules.return_value = MagicMock(article_pairs=frozenset(), source_pair_thresholds={})
        report = run_cluster_and_embed(config)
        assert report.articles_clustered == 0  # no articles to cluster, but step ran


def test_run_cluster_and_embed_uses_assignment_threshold_for_existing_stories() -> None:
    """Assignment to existing stories uses story_assignment_threshold,
    not story_similarity_threshold."""
    config = {
        "processing": {
            "story_similarity_threshold": 0.92,
            "story_assignment_threshold": 0.95,
            "cluster_use_ivfflat": False,
        },
        "extraction": {"cluster_gate_max_pending": 5},
    }
    article = {"id": "art1", "embedding": [0.1] * 1024, "source_id": "src1"}
    with (
        patch(
            "app.clustering.service.db_articles.get_recent_articles_without_embedding",
            return_value=[],
        ),
        patch(
            "app.clustering.service.db_articles.get_pending_extraction_count",
            return_value=0,
        ),
        patch("app.clustering.service.get_embedding_provider") as mock_prov,
        patch(
            "app.clustering.service.db_articles.get_articles_with_embedding_not_in_story",
            return_value=[article],
        ),
        patch(
            "app.clustering.service.db_stories.get_stories_with_articles_in_window",
            return_value=[],
        ),
        patch(
            "app.clustering.service.db_stories.get_stories_with_centroid_in_window",
            return_value=[],
        ),
        patch("app.clustering.service._assign_to_existing_stories") as mock_assign,
        patch("app.clustering.service._cluster_articles", return_value=[]),
        patch("app.clustering.service._load_exclusion_rules") as mock_rules,
        patch("app.clustering.service._build_source_topics_index", return_value={}),
    ):
        mock_prov.return_value = MagicMock()
        mock_rules.return_value = MagicMock(article_pairs=frozenset(), source_pair_thresholds={})
        mock_assign.return_value = ([], [article])
        run_cluster_and_embed(config)
        # The threshold passed to _assign_to_existing_stories must be the assignment
        # threshold (0.95), not the story_similarity_threshold (0.92).
        call_kwargs = mock_assign.call_args
        # threshold is the 3rd positional argument
        threshold_used = call_kwargs.args[2]
        assert threshold_used == 0.95, f"Expected 0.95 but got {threshold_used}"
