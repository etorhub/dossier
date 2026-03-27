"""Tests for discovery validation module."""

from unittest.mock import patch

from app.discovery.validation import check_dns, validate_source


@patch("app.discovery.validation.socket.gethostbyname", return_value="142.250.0.1")
def test_check_dns_resolves_google(mock_gethostbyname: object) -> None:
    """check_dns returns True when gethostbyname succeeds."""
    assert check_dns("www.google.com") is True


def test_check_dns_fails_for_nonexistent() -> None:
    """Non-existent domain fails."""
    assert check_dns("this-domain-does-not-exist-12345.invalid") is False


def test_validate_source_empty_domain() -> None:
    """Empty domain fails validation."""
    result = validate_source("")
    assert result["passed"] is False
    assert "No domain provided" in result["errors"]


def test_validate_source_nonexistent_domain() -> None:
    """Non-existent domain fails."""
    result = validate_source("nonexistent-domain-xyz-12345.invalid")
    assert result["passed"] is False
    assert result["dns_ok"] is False


@patch("app.discovery.validation.check_https")
@patch("app.discovery.validation.check_dns")
def test_validate_source_all_pass(mock_dns: object, mock_https: object) -> None:
    """When DNS and HTTPS pass, validation passes if robots allows."""
    mock_dns.return_value = True
    mock_https.return_value = True
    with patch("app.discovery.validation.check_robots_txt", return_value=True):
        result = validate_source("www.example.com")
    assert result["dns_ok"] is True
    assert result["https_ok"] is True
    assert result["robots_ok"] is True
    assert result["passed"] is True
    assert result["errors"] == []
