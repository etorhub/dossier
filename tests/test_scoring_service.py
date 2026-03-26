"""Unit tests for relevance scoring_service."""

from datetime import UTC, datetime, timedelta
from typing import Any

from app.services.scoring_service import (
    _content_quality_score,
    _coverage_score,
    _recency_score,
    _topic_affinity_score,
    score_cluster,
)


def test_recency_score_just_now() -> None:
    """Article published now scores ~1.0."""
    now = datetime.now(UTC)
    articles = [{"published_at": now}]
    assert _recency_score(articles, 8) >= 0.999


def test_recency_score_half_life() -> None:
    """Article at half_life hours ago scores ~0.5."""
    half_life = 8
    ago = datetime.now(UTC) - timedelta(hours=half_life)
    articles = [{"published_at": ago}]
    score = _recency_score(articles, half_life)
    assert 0.49 <= score <= 0.51


def test_recency_score_old() -> None:
    """Article 24h ago scores low."""
    ago = datetime.now(UTC) - timedelta(hours=24)
    articles = [{"published_at": ago}]
    score = _recency_score(articles, 8)
    assert score < 0.2


def test_recency_score_empty_articles() -> None:
    """Empty articles returns 0."""
    assert _recency_score([], 8) == 0.0


def test_recency_score_no_published_at() -> None:
    """Articles without published_at return 0."""
    articles = [{"source_id": "s1"}]
    assert _recency_score(articles, 8) == 0.0


def test_coverage_score_single_source() -> None:
    """One distinct source with cap 4 scores 0.25."""
    articles = [{"source_id": "s1"}, {"source_id": "s1"}]
    assert _coverage_score(articles, 4) == 0.25


def test_coverage_score_four_sources() -> None:
    """Four distinct sources with cap 4 scores 1.0."""
    articles = [
        {"source_id": "s1"},
        {"source_id": "s2"},
        {"source_id": "s3"},
        {"source_id": "s4"},
    ]
    assert _coverage_score(articles, 4) == 1.0


def test_coverage_score_capped() -> None:
    """More than cap sources still scores 1.0."""
    articles = [{"source_id": f"s{i}"} for i in range(10)]
    assert _coverage_score(articles, 4) == 1.0


def test_coverage_score_empty() -> None:
    """Empty articles returns 0."""
    assert _coverage_score([], 4) == 0.0


def test_topic_affinity_all_match() -> None:
    """All articles from sources with user topics scores 1.0."""
    articles = [
        {"source_id": "s1"},
        {"source_id": "s2"},
    ]
    sources = {
        "s1": {"topics": ["politics"]},
        "s2": {"topics": ["general"]},
    }
    user_topics = {"politics", "general"}
    assert _topic_affinity_score(articles, user_topics, sources) == 1.0


def test_topic_affinity_half_match() -> None:
    """Half of articles match scores 0.5."""
    articles = [
        {"source_id": "s1"},
        {"source_id": "s2"},
    ]
    sources = {
        "s1": {"topics": ["politics"]},
        "s2": {"topics": ["culture"]},
    }
    user_topics = {"politics"}
    assert _topic_affinity_score(articles, user_topics, sources) == 0.5


def test_topic_affinity_no_match() -> None:
    """No topic overlap scores 0."""
    articles = [{"source_id": "s1"}]
    sources = {"s1": {"topics": ["culture"]}}
    user_topics = {"politics"}
    assert _topic_affinity_score(articles, user_topics, sources) == 0.0


def test_topic_affinity_empty_user_topics() -> None:
    """Empty user topics returns 0."""
    articles = [{"source_id": "s1"}]
    sources = {"s1": {"topics": ["politics"]}}
    assert _topic_affinity_score(articles, set(), sources) == 0.0


def test_content_quality_all_extracted() -> None:
    """All articles extracted scores 1.0."""
    articles = [
        {"extraction_status": "extracted"},
        {"extraction_status": "extracted"},
    ]
    assert _content_quality_score(articles) == 1.0


def test_content_quality_half_extracted() -> None:
    """Half extracted scores 0.5."""
    articles = [
        {"extraction_status": "extracted"},
        {"extraction_status": "pending"},
    ]
    assert _content_quality_score(articles) == 0.5


def test_content_quality_none_extracted() -> None:
    """None extracted scores 0."""
    articles = [
        {"extraction_status": "pending"},
        {"extraction_status": "failed"},
    ]
    assert _content_quality_score(articles) == 0.0


def test_content_quality_empty() -> None:
    """Empty articles returns 0."""
    assert _content_quality_score([]) == 0.0


def test_score_cluster_composite() -> None:
    """Composite score combines recency, coverage, topic, and quality with weights."""
    now = datetime.now(UTC)
    cluster_data: dict[str, Any] = {
        "cluster_id": "c1",
        "articles": [
            {"source_id": "s1", "published_at": now, "extraction_status": "extracted"},
            {"source_id": "s2", "published_at": now, "extraction_status": "extracted"},
        ],
    }
    sources = {
        "s1": {"topics": ["politics"]},
        "s2": {"topics": ["general"]},
    }
    config = {
        "relevance": {
            "weights": {
                "recency": 0.30,
                "coverage": 0.25,
                "topic_affinity": 0.25,
                "content_quality": 0.20,
            },
            "recency_half_life_hours": 8,
            "coverage_cap": 4,
        }
    }
    score = score_cluster(
        cluster_data,
        user_topic_ids={"politics", "general"},
        sources_catalog=sources,
        config=config,
    )
    # Recency~1, coverage=0.5 (2/4), topic=1, quality=1
    # -> 0.30 + 0.125 + 0.25 + 0.20 = 0.875
    assert 0.87 <= score <= 0.88
    assert score <= 1.0


def test_score_cluster_empty_articles() -> None:
    """Empty cluster scores 0."""
    cluster_data = {"cluster_id": "c1", "articles": []}
    config = {"relevance": {"weights": {}, "recency_half_life_hours": 8, "coverage_cap": 4}}
    score = score_cluster(
        cluster_data,
        user_topic_ids={"politics"},
        sources_catalog={},
        config=config,
    )
    assert score == 0.0


def test_score_cluster_uses_default_weights() -> None:
    """Works with empty config (defaults)."""
    now = datetime.now(UTC)
    cluster_data = {
        "articles": [
            {"source_id": "s1", "published_at": now, "extraction_status": "extracted"},
        ],
    }
    sources = {"s1": {"topics": ["politics"]}}
    score = score_cluster(
        cluster_data,
        user_topic_ids={"politics"},
        sources_catalog=sources,
        config={},
    )
    assert 0 < score <= 1.0


def test_score_cluster_default_weights_favor_coverage() -> None:
    """Default weights: multi-source cluster outscores singleton at same recency."""
    now = datetime.now(UTC)
    sources = {
        "s1": {"topics": ["politics"]},
        "s2": {"topics": ["politics"]},
    }
    singleton = {
        "articles": [
            {"source_id": "s1", "published_at": now, "extraction_status": "extracted"},
        ],
    }
    multi_source = {
        "articles": [
            {"source_id": "s1", "published_at": now, "extraction_status": "extracted"},
            {"source_id": "s2", "published_at": now, "extraction_status": "extracted"},
        ],
    }
    user_topics = {"politics"}
    config = {}  # defaults: recency 0.30, coverage 0.40, etc.

    score_singleton = score_cluster(singleton, user_topics, sources, config)
    score_multi = score_cluster(multi_source, user_topics, sources, config)
    assert score_multi > score_singleton
