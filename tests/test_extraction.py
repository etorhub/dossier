"""Tests for extraction module."""

import logging
from unittest.mock import MagicMock, call, patch

import pytest

from app.db import articles as articles_db
from app.db.connection import get_connection, return_connection
from app.extraction.extractor import _domain_from_url, enrich_articles
from app.extraction.trafilatura import extract_article


def _has_db() -> bool:
    """Check if we can connect to the database."""
    try:
        conn = get_connection()
        return_connection(conn)
        return True
    except Exception:
        return False


def _cleanup_test_extraction_articles() -> None:
    """Remove test articles used by extraction tests."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM articles WHERE source_id = %s",
                ("test_extraction_src",),
            )
        conn.commit()
    finally:
        return_connection(conn)


def test_domain_from_url() -> None:
    """_domain_from_url extracts netloc from URL."""
    assert _domain_from_url("https://www.example.com/path") == "www.example.com"
    assert _domain_from_url("https://example.com") == "example.com"


def _mock_extract_txt_only(txt: str | None) -> object:
    """Side-effect: xml pass returns empty main, txt pass returns ``txt``."""

    def _side_effect(_html: str, **kwargs: object) -> str | None:
        if kwargs.get("output_format") == "xml":
            return "<doc><main></main></doc>"
        return txt

    return _side_effect


@patch("app.extraction.trafilatura.trafilatura.fetch_url")
@patch("app.extraction.trafilatura.trafilatura.extract")
def test_extract_article_success(mock_extract, mock_fetch) -> None:
    """extract_article returns (text, body_image, og_image) when extraction succeeds."""
    mock_fetch.return_value = "<html><body><article>Hello world</article></body></html>"
    mock_extract.side_effect = _mock_extract_txt_only("Hello world")

    text, body_img, og_image = extract_article("https://example.com/article")
    assert text == "Hello world"
    assert body_img is None
    assert og_image is None
    mock_fetch.assert_called_once()
    assert mock_extract.call_count == 2


@patch("app.extraction.trafilatura.trafilatura.fetch_url")
def test_extract_article_fetch_fails(mock_fetch) -> None:
    """extract_article returns (None, None, None) when fetch fails."""
    mock_fetch.return_value = None

    text, body_img, og_image = extract_article("https://example.com/article")
    assert text is None
    assert body_img is None
    assert og_image is None


@patch("app.extraction.trafilatura.trafilatura.fetch_url")
@patch("app.extraction.trafilatura.trafilatura.extract")
def test_extract_article_extract_returns_empty(mock_extract, mock_fetch) -> None:
    """extract_article returns (None, None, None) when txt extract returns empty."""
    mock_fetch.return_value = "<html></html>"
    mock_extract.side_effect = _mock_extract_txt_only(None)

    text, body_img, og_image = extract_article("https://example.com/article")
    assert text is None
    assert body_img is None
    assert og_image is None


@patch("app.extraction.trafilatura.trafilatura.fetch_url")
@patch("app.extraction.trafilatura.trafilatura.extract")
def test_extract_article_extract_returns_whitespace(mock_extract, mock_fetch) -> None:
    """extract_article returns three Nones when extract returns only whitespace."""
    mock_fetch.return_value = "<html></html>"
    mock_extract.side_effect = _mock_extract_txt_only("   \n  ")

    text, body_img, og_image = extract_article("https://example.com/article")
    assert text is None
    assert body_img is None
    assert og_image is None


@patch("app.extraction.trafilatura.trafilatura.fetch_url")
@patch("app.extraction.trafilatura.trafilatura.extract")
def test_extract_article_extracts_og_image(mock_extract, mock_fetch) -> None:
    """extract_article extracts og:image from HTML when present."""
    html_with_og = (
        '<html><head><meta property="og:image" content="https://example.com/og.jpg" />'
        "</head><body></body></html>"
    )
    mock_fetch.return_value = html_with_og
    mock_extract.side_effect = _mock_extract_txt_only("Article text")

    text, body_img, og_image = extract_article("https://example.com/article")
    assert text == "Article text"
    assert body_img is None
    assert og_image == "https://example.com/og.jpg"


@patch("app.extraction.trafilatura.trafilatura.fetch_url")
@patch("app.extraction.trafilatura.trafilatura.extract")
def test_extract_article_prefers_body_graphic_over_og(mock_extract, mock_fetch) -> None:
    """First <graphic> in extracted main wins over og:image."""
    html_with_og = (
        '<html><head><meta property="og:image" content="https://example.com/og.jpg" />'
        "</head><body></body></html>"
    )
    mock_fetch.return_value = html_with_og

    def _side_effect(_html: str, **kwargs: object) -> str | None:
        if kwargs.get("output_format") == "xml":
            return (
                '<doc><main><graphic src="https://example.com/in-article.jpg"/>'
                "<p>Body</p></main></doc>"
            )
        return "Article text"

    mock_extract.side_effect = _side_effect

    text, body_img, og_image = extract_article("https://example.com/article")
    assert text == "Article text"
    assert body_img == "https://example.com/in-article.jpg"
    assert og_image == "https://example.com/og.jpg"


def test_enrich_articles_disabled_returns_empty_report() -> None:
    """enrich_articles returns zeros when extraction is disabled."""
    config = {"extraction": {"enabled": False}}
    report = enrich_articles(config)
    assert report.articles_checked == 0
    assert report.articles_extracted == 0
    assert report.articles_failed == 0
    assert report.articles_skipped == 0


@pytest.mark.skipif(not _has_db(), reason="Database not available")
def test_get_articles_needing_extraction() -> None:
    """get_articles_needing_extraction returns pending articles."""
    _cleanup_test_extraction_articles()
    article = {
        "source_id": "test_extraction_src",
        "title": "Pending Article",
        "url": "https://test.example.com/pending",
    }
    try:
        articles_db.insert_article(article)
        # New articles get extraction_status='pending' via server default
        candidates = articles_db.get_articles_needing_extraction(limit=10)
        found = next(
            (a for a in candidates if a["source_id"] == "test_extraction_src"), None
        )
        assert found is not None
        assert found["url"] == "https://test.example.com/pending"
    finally:
        _cleanup_test_extraction_articles()


@pytest.mark.skipif(not _has_db(), reason="Database not available")
def test_update_article_extraction() -> None:
    """update_article_extraction updates article with extraction result."""
    _cleanup_test_extraction_articles()
    article = {
        "source_id": "test_extraction_src",
        "title": "Update Test",
        "url": "https://test.example.com/update",
    }
    try:
        inserted = articles_db.insert_article(article)
        assert inserted is True
        art = articles_db.get_articles_needing_extraction(limit=50)
        row = next(
            (a for a in art if a["url"] == "https://test.example.com/update"),
            None,
        )
        assert row is not None
        article_id = row["id"]

        articles_db.update_article_extraction(
            article_id, "Extracted full text.", "extracted", "trafilatura"
        )

        updated = articles_db.get_article_by_id(article_id)
        assert updated is not None
        assert updated["full_text"] == "Extracted full text."
        assert updated["extraction_status"] == "extracted"
        assert updated["extraction_method"] == "trafilatura"
        assert updated["extracted_at"] is not None
    finally:
        _cleanup_test_extraction_articles()


@pytest.mark.skipif(not _has_db(), reason="Database not available")
def test_update_article_extraction_replace_image_overwrites() -> None:
    """replace_image=True overwrites an existing image_url."""
    _cleanup_test_extraction_articles()
    article = {
        "source_id": "test_extraction_src",
        "title": "Img Replace",
        "url": "https://test.example.com/img-replace",
        "image_url": "https://old.example.com/old.jpg",
        "image_source": "media_thumbnail",
    }
    try:
        assert articles_db.insert_article(article) is True
        art = articles_db.get_articles_needing_extraction(limit=50)
        row = next(
            (a for a in art if a["url"] == "https://test.example.com/img-replace"),
            None,
        )
        assert row is not None
        article_id = row["id"]

        articles_db.update_article_extraction(
            article_id,
            "Text.",
            "extracted",
            "trafilatura",
            image_url="https://new.example.com/new.jpg",
            image_source="article_body",
            replace_image=True,
        )
        updated = articles_db.get_article_by_id(article_id)
        assert updated is not None
        assert updated["image_url"] == "https://new.example.com/new.jpg"
        assert updated["image_source"] == "article_body"
    finally:
        _cleanup_test_extraction_articles()


# ---------------------------------------------------------------------------
# enrich_all_articles abandonment logic (no DB required)
# ---------------------------------------------------------------------------


def test_enrich_all_articles_abandons_stale_pending() -> None:
    """abandon_stale_pending_articles is called with the configured hours value."""
    config = {"extraction": {"enabled": True, "abandon_after_hours": 4}}
    with patch("app.extraction.extractor.db_articles.abandon_stale_pending_articles", return_value=3) as mock_abandon, \
         patch("app.extraction.extractor.db_articles.get_pending_extraction_count", return_value=0):
        from app.extraction.extractor import enrich_all_articles
        enrich_all_articles(config)
        mock_abandon.assert_called_once_with(4)


def test_enrich_all_articles_skips_abandon_when_hours_zero() -> None:
    """abandon_stale_pending_articles is NOT called when abandon_after_hours=0."""
    config = {"extraction": {"enabled": True, "abandon_after_hours": 0}}
    with patch("app.extraction.extractor.db_articles.abandon_stale_pending_articles") as mock_abandon, \
         patch("app.extraction.extractor.db_articles.get_pending_extraction_count", return_value=0):
        from app.extraction.extractor import enrich_all_articles
        enrich_all_articles(config)
        mock_abandon.assert_not_called()


def test_enrich_all_articles_logs_warning_when_articles_abandoned(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A WARNING is logged when abandon_stale_pending_articles returns > 0."""
    config = {"extraction": {"enabled": True, "abandon_after_hours": 4}}
    with patch("app.extraction.extractor.db_articles.abandon_stale_pending_articles", return_value=2), \
         patch("app.extraction.extractor.db_articles.get_pending_extraction_count", return_value=0):
        from app.extraction.extractor import enrich_all_articles
        with caplog.at_level(logging.WARNING, logger="app.extraction.extractor"):
            enrich_all_articles(config)
    assert any("Abandoned" in r.message and "2" in r.message for r in caplog.records)


def test_enrich_all_articles_no_warning_when_none_abandoned(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """No abandonment WARNING is logged when abandon_stale_pending_articles returns 0."""
    config = {"extraction": {"enabled": True, "abandon_after_hours": 4}}
    with patch("app.extraction.extractor.db_articles.abandon_stale_pending_articles", return_value=0), \
         patch("app.extraction.extractor.db_articles.get_pending_extraction_count", return_value=0):
        from app.extraction.extractor import enrich_all_articles
        with caplog.at_level(logging.WARNING, logger="app.extraction.extractor"):
            enrich_all_articles(config)
    assert not any("Abandoned" in r.message for r in caplog.records)


def test_enrich_all_articles_uses_default_abandon_hours() -> None:
    """abandon_stale_pending_articles is called with default of 4 when not configured."""
    config = {"extraction": {"enabled": True}}
    with patch("app.extraction.extractor.db_articles.abandon_stale_pending_articles", return_value=0) as mock_abandon, \
         patch("app.extraction.extractor.db_articles.get_pending_extraction_count", return_value=0):
        from app.extraction.extractor import enrich_all_articles
        enrich_all_articles(config)
        mock_abandon.assert_called_once_with(4)
