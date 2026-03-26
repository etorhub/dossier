"""Tests for db/articles module.

Uses real database when DATABASE_URL is set (e.g. in Docker).
Skips when no database available.
"""

from datetime import UTC, datetime

import pytest

from app.db import articles as articles_db
from app.db.connection import get_connection, return_connection


def _has_db() -> bool:
    """Check if we can connect to the database."""
    try:
        conn = get_connection()
        return_connection(conn)
        return True
    except Exception:
        return False


def _cleanup_test_articles() -> None:
    """Remove test articles."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM articles WHERE source_id = %s",
                ("test_article_src_789",),
            )
        conn.commit()
    finally:
        return_connection(conn)


@pytest.mark.skipif(not _has_db(), reason="Database not available")
def test_insert_article_returns_true() -> None:
    """First insert returns True."""
    _cleanup_test_articles()
    article = {
        "source_id": "test_article_src_789",
        "title": "Test Article",
        "url": "https://test.example.com/unique-1",
    }
    try:
        inserted = articles_db.insert_article(article)
        assert inserted is True
    finally:
        _cleanup_test_articles()


@pytest.mark.skipif(not _has_db(), reason="Database not available")
def test_insert_article_dedup_returns_false() -> None:
    """Duplicate insert (same source_id+url) returns False."""
    _cleanup_test_articles()
    article = {
        "source_id": "test_article_src_789",
        "title": "Dup Article",
        "url": "https://test.example.com/dup-url",
    }
    try:
        first = articles_db.insert_article(article)
        second = articles_db.insert_article(article)
        assert first is True
        assert second is False
    finally:
        _cleanup_test_articles()


@pytest.mark.skipif(not _has_db(), reason="Database not available")
def test_article_exists() -> None:
    """article_exists returns True after insert, False otherwise."""
    _cleanup_test_articles()
    article = {
        "source_id": "test_article_src_789",
        "title": "Exists Test",
        "url": "https://test.example.com/exists",
    }
    try:
        src_id, url = "test_article_src_789", article["url"]
        assert articles_db.article_exists(src_id, url) is False
        articles_db.insert_article(article)
        assert articles_db.article_exists(src_id, url) is True
    finally:
        _cleanup_test_articles()


@pytest.mark.skipif(not _has_db(), reason="Database not available")
def test_get_recent_articles() -> None:
    """get_recent_articles returns articles since given datetime."""
    _cleanup_test_articles()
    now = datetime.now(UTC)
    article = {
        "source_id": "test_article_src_789",
        "title": "Recent Test",
        "url": "https://test.example.com/recent",
        "published_at": now,
    }
    try:
        articles_db.insert_article(article)
        recent = articles_db.get_recent_articles(now.replace(year=now.year - 1))
        assert len(recent) >= 1
        found = next((a for a in recent if a["source_id"] == "test_article_src_789"), None)
        assert found is not None
        assert found["title"] == "Recent Test"

        filtered = articles_db.get_recent_articles(
            now.replace(year=now.year - 1), source_id="test_article_src_789"
        )
        assert len(filtered) >= 1
    finally:
        _cleanup_test_articles()
