"""Unit tests for clustering embedding helpers."""

from app.clustering.embed_status import _cluster_result_summary
from app.clustering.service import _embedding_from_article


def test_embedding_from_article_empty_list_is_invalid() -> None:
    assert _embedding_from_article({"id": "x", "embedding": []}) is None


def test_embedding_from_article_nonempty_list_preserved() -> None:
    v = [0.1, 0.2]
    assert _embedding_from_article({"id": "x", "embedding": v}) == v


def test_cluster_result_summary_dict() -> None:
    out = _cluster_result_summary(
        {"articles_embedded": 3, "articles_clustered": 10, "stories_created": 2}
    )
    assert out == {
        "articles_embedded": 3,
        "articles_clustered": 10,
        "stories_created": 2,
    }


def test_cluster_result_summary_json_string() -> None:
    raw = '{"articles_embedded": 1, "articles_clustered": 5, "stories_created": 0}'
    out = _cluster_result_summary(raw)
    assert out == {
        "articles_embedded": 1,
        "articles_clustered": 5,
        "stories_created": 0,
    }
