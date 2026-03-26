"""Tests for discovery feed_detection module."""

from unittest.mock import MagicMock, patch

from app.discovery.feed_detection import validate_feed


def test_validate_feed_invalid_url() -> None:
    """Invalid or unreachable URL returns error."""
    result = validate_feed("https://invalid-domain-that-does-not-resolve-12345.invalid/feed")
    assert result["ok"] is False
    assert result["error"] is not None


@patch("app.discovery.feed_detection.httpx")
def test_validate_feed_http_error(mock_httpx: MagicMock) -> None:
    """HTTP non-200 returns error."""
    mock_resp = MagicMock()
    mock_resp.status_code = 404
    mock_client = MagicMock()
    mock_client.get.return_value = mock_resp
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_httpx.Client.return_value = mock_client

    result = validate_feed("https://example.com/feed")
    assert result["ok"] is False
    assert "404" in str(result["error"])


@patch("app.discovery.feed_detection.httpx")
def test_validate_feed_valid_rss(mock_httpx: MagicMock) -> None:
    """Valid RSS XML returns ok with item count."""
    rss_body = """<?xml version="1.0"?>
    <rss version="2.0">
    <channel>
        <title>Test Feed</title>
        <item>
            <title>Item 1</title>
            <link>https://example.com/1</link>
            <description>Desc 1</description>
            <pubDate>Mon, 01 Jan 2024 12:00:00 GMT</pubDate>
        </item>
    </channel>
    </rss>"""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = rss_body
    mock_resp.headers = {"Content-Type": "application/rss+xml"}
    mock_client = MagicMock()
    mock_client.get.return_value = mock_resp
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    mock_httpx.Client.return_value = mock_client

    result = validate_feed("https://example.com/feed")
    assert result["ok"] is True
    assert result["item_count"] >= 1
    assert result["feed_type"] in ("rss", "atom")
    assert result["completeness_pct"] >= 0
