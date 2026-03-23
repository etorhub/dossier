"""Unit tests for clustering embedding helpers."""

from app.clustering.service import _embedding_from_article


def test_embedding_from_article_empty_list_is_invalid() -> None:
    assert _embedding_from_article({"id": "x", "embedding": []}) is None


def test_embedding_from_article_nonempty_list_preserved() -> None:
    v = [0.1, 0.2]
    assert _embedding_from_article({"id": "x", "embedding": v}) == v
