"""Tests for feed orchestrator."""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

from app.feed.orchestrator import fetch_all_due_feeds


@patch("app.feed.orchestrator.sources_db")
@patch("app.feed.orchestrator.fetch_feed")
@patch("app.feed.orchestrator.parse_feed")
@patch("app.feed.orchestrator.articles_db")
def test_fetch_all_due_feeds_empty(
    mock_articles: MagicMock,
    mock_parse: MagicMock,
    mock_fetch: MagicMock,
    mock_sources: MagicMock,
) -> None:
    """When no feeds are due, report is zero."""
    mock_sources.get_all_active_feeds.return_value = []
    report = fetch_all_due_feeds({})
    assert report.feeds_checked == 0
    assert report.feeds_fetched == 0
    assert report.articles_inserted == 0
    mock_fetch.assert_not_called()


@patch("app.feed.orchestrator.sources_db")
@patch("app.feed.orchestrator.fetch_feed")
@patch("app.feed.orchestrator.parse_feed")
@patch("app.feed.orchestrator.articles_db")
def test_fetch_all_due_feeds_304_not_modified(
    mock_articles: MagicMock,
    mock_parse: MagicMock,
    mock_fetch: MagicMock,
    mock_sources: MagicMock,
) -> None:
    """304 response updates last_fetched_at and skips parse."""
    from app.feed.fetcher import FetchResult

    mock_sources.get_all_active_feeds.return_value = [
        {
            "id": 1,
            "source_id": "src1",
            "feed_url": "https://example.com/feed",
            "last_fetched_at": None,
            "poll_interval_minutes": 60,
            "full_text_available": False,
        }
    ]
    mock_fetch.return_value = FetchResult(
        status_code=304,
        content=None,
        etag='"x"',
        last_modified="Mon, 01 Jan 2024 00:00:00 GMT",
        is_not_modified=True,
    )

    report = fetch_all_due_feeds({})

    assert report.feeds_checked == 1
    assert report.feeds_fetched == 1
    assert report.articles_inserted == 0
    mock_parse.assert_not_called()
    mock_sources.update_feed.assert_called_once()
    call_kwargs = mock_sources.update_feed.call_args[1]
    assert "last_fetched_at" in call_kwargs


@patch("app.feed.orchestrator.sources_db")
@patch("app.feed.orchestrator.fetch_feed")
@patch("app.feed.orchestrator.parse_feed")
@patch("app.feed.orchestrator.articles_db")
def test_fetch_all_due_feeds_inserts_articles(
    mock_articles: MagicMock,
    mock_parse: MagicMock,
    mock_fetch: MagicMock,
    mock_sources: MagicMock,
) -> None:
    """Successful fetch parses and inserts articles."""
    from app.feed.fetcher import FetchResult

    mock_sources.get_all_active_feeds.return_value = [
        {
            "id": 1,
            "source_id": "src1",
            "feed_url": "https://example.com/feed",
            "last_fetched_at": None,
            "poll_interval_minutes": 60,
            "full_text_available": True,
        }
    ]
    mock_fetch.return_value = FetchResult(
        status_code=200,
        content=b"<rss></rss>",
        etag='"y"',
        last_modified=None,
        is_not_modified=False,
    )
    mock_parse.return_value = [
        {
            "guid": "g1",
            "title": "Art 1",
            "url": "https://example.com/1",
            "published_at": None,
            "raw_text": "Summary",
            "full_text": "Full body",
        }
    ]
    mock_articles.insert_article.return_value = True

    report = fetch_all_due_feeds({})

    assert report.feeds_checked == 1
    assert report.feeds_fetched == 1
    assert report.articles_inserted == 1
    mock_parse.assert_called_once()
    mock_articles.insert_article.assert_called_once()
    call_arg = mock_articles.insert_article.call_args[0][0]
    assert call_arg["source_id"] == "src1"
    assert call_arg["title"] == "Art 1"
    assert call_arg["full_text"] == "Full body"
    mock_sources.update_feed.assert_called_once()
    call_kwargs = mock_sources.update_feed.call_args[1]
    assert call_kwargs["consecutive_failures"] == 0


@patch("app.feed.orchestrator.sources_db")
@patch("app.feed.orchestrator.fetch_feed")
def test_fetch_all_due_feeds_circuit_breaker(
    mock_fetch: MagicMock,
    mock_sources: MagicMock,
) -> None:
    """After threshold failures, feed is deactivated."""
    mock_sources.get_all_active_feeds.return_value = [
        {
            "id": 1,
            "source_id": "src1",
            "feed_url": "https://example.com/feed",
            "last_fetched_at": None,
            "poll_interval_minutes": 60,
            "consecutive_failures": 4,
            "full_text_available": False,
        }
    ]
    mock_fetch.side_effect = Exception("Connection refused")

    report = fetch_all_due_feeds({"schedule": {"fetcher": {"circuit_breaker_threshold": 5}}})

    assert report.feeds_deactivated == 1
    mock_sources.update_feed.assert_called()
    deactivate_call = next(
        c for c in mock_sources.update_feed.call_args_list if c[1].get("feed_active") is False
    )
    assert deactivate_call is not None


@patch("app.feed.orchestrator.sources_db")
def test_fetch_all_due_feeds_filters_by_due(mock_sources: MagicMock) -> None:
    """Only feeds past their poll interval are fetched."""
    now = datetime.now(UTC)
    recent = (now - timedelta(minutes=5)).isoformat()
    mock_sources.get_all_active_feeds.return_value = [
        {
            "id": 1,
            "source_id": "src1",
            "feed_url": "https://example.com/feed",
            "last_fetched_at": recent,
            "poll_interval_minutes": 60,
            "full_text_available": False,
        }
    ]

    report = fetch_all_due_feeds({})

    assert report.feeds_checked == 0
