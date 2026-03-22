"""Tests for feed fetcher."""

from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.feed.fetcher import fetch_feed


@patch("app.feed.fetcher.httpx.Client")
def test_fetch_feed_200(mock_client_class: MagicMock) -> None:
    """Successful fetch returns content and metadata."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = b"<rss>content</rss>"
    mock_resp.headers = {
        "ETag": '"abc"',
        "Last-Modified": "Mon, 01 Jan 2024 00:00:00 GMT",
    }

    mock_client = MagicMock()
    mock_client.get.return_value = mock_resp
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client_class.return_value = mock_client

    result = fetch_feed("https://example.com/feed")

    assert result.status_code == 200
    assert result.content == b"<rss>content</rss>"
    assert result.etag == '"abc"'
    assert result.last_modified == "Mon, 01 Jan 2024 00:00:00 GMT"
    assert result.is_not_modified is False

    mock_client.get.assert_called_once()
    call_kwargs = mock_client.get.call_args[1]
    assert call_kwargs["headers"]["User-Agent"] == "Dossier/0.1"


@patch("app.feed.fetcher.httpx.Client")
def test_fetch_feed_304_not_modified(mock_client_class: MagicMock) -> None:
    """304 response returns is_not_modified and no content."""
    mock_resp = MagicMock()
    mock_resp.status_code = 304

    mock_client = MagicMock()
    mock_client.get.return_value = mock_resp
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client_class.return_value = mock_client

    result = fetch_feed(
        "https://example.com/feed",
        etag='"old-etag"',
        last_modified="Mon, 01 Jan 2024 00:00:00 GMT",
    )

    assert result.status_code == 304
    assert result.content is None
    assert result.is_not_modified is True
    assert "If-None-Match" in mock_client.get.call_args[1]["headers"]
    assert "If-Modified-Since" in mock_client.get.call_args[1]["headers"]


@patch("app.feed.fetcher.httpx.Client")
def test_fetch_feed_conditional_headers_sent(mock_client_class: MagicMock) -> None:
    """Etag and last_modified are sent as conditional headers when provided."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = b"content"
    mock_resp.headers = {}

    mock_client = MagicMock()
    mock_client.get.return_value = mock_resp
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client_class.return_value = mock_client

    fetch_feed(
        "https://example.com/feed",
        etag='"x"',
        last_modified="Wed, 01 Jan 2024 00:00:00 GMT",
    )

    headers = mock_client.get.call_args[1]["headers"]
    assert headers["If-None-Match"] == '"x"'
    assert headers["If-Modified-Since"] == "Wed, 01 Jan 2024 00:00:00 GMT"


@patch("app.feed.fetcher.httpx.Client")
def test_fetch_feed_http_error_raises(mock_client_class: MagicMock) -> None:
    """HTTP errors (e.g. connection) are propagated."""
    mock_client = MagicMock()
    mock_client.get.side_effect = httpx.ConnectError("Connection refused")
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_client_class.return_value = mock_client

    with pytest.raises(httpx.ConnectError):
        fetch_feed("https://example.com/feed")
