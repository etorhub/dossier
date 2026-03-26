"""Tests for AnthropicLLMProvider and helpers in app/llm/anthropic_llm.py."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.llm.anthropic_llm import (
    DEFAULT_ANTHROPIC_API_BASE,
    AnthropicLLMProvider,
    _extract_anthropic_text,
)
from app.llm.provider import LLMProviderError


# ---------------------------------------------------------------------------
# _extract_anthropic_text
# ---------------------------------------------------------------------------


def test_extract_anthropic_text_returns_concatenated_text() -> None:
    """_extract_anthropic_text joins multiple text blocks."""
    data = {
        "content": [
            {"type": "text", "text": "Hello "},
            {"type": "text", "text": "world"},
        ]
    }
    assert _extract_anthropic_text(data) == "Hello world"


def test_extract_anthropic_text_skips_non_text_blocks() -> None:
    """_extract_anthropic_text ignores blocks that are not type=text."""
    data = {
        "content": [
            {"type": "tool_use", "id": "x", "name": "foo", "input": {}},
            {"type": "text", "text": "result"},
        ]
    }
    assert _extract_anthropic_text(data) == "result"


def test_extract_anthropic_text_returns_empty_when_content_missing() -> None:
    """_extract_anthropic_text returns '' when 'content' key is absent."""
    assert _extract_anthropic_text({}) == ""


def test_extract_anthropic_text_returns_empty_when_content_not_list() -> None:
    """_extract_anthropic_text returns '' when content is not a list."""
    assert _extract_anthropic_text({"content": "not a list"}) == ""


def test_extract_anthropic_text_ignores_blocks_with_empty_text() -> None:
    """_extract_anthropic_text skips blocks with falsy text."""
    data = {"content": [{"type": "text", "text": ""}, {"type": "text", "text": "hi"}]}
    assert _extract_anthropic_text(data) == "hi"


# ---------------------------------------------------------------------------
# AnthropicLLMProvider.from_llm_config
# ---------------------------------------------------------------------------


def test_from_llm_config_defaults() -> None:
    """from_llm_config applies defaults when the config dict is empty."""
    p = AnthropicLLMProvider.from_llm_config({})
    assert p._model == "claude-3-5-sonnet-20241022"
    assert p._api_base == DEFAULT_ANTHROPIC_API_BASE
    assert p._timeout_seconds == 120.0
    assert p._max_retries == 3


def test_from_llm_config_reads_all_fields() -> None:
    """from_llm_config picks up model, api_base, timeout, retries from config."""
    cfg = {
        "model": "claude-3-opus-20240229",
        "api_base": "https://my-proxy.example.com",
        "timeout_seconds": 60,
        "max_retries": 5,
    }
    p = AnthropicLLMProvider.from_llm_config(cfg)
    assert p._model == "claude-3-opus-20240229"
    assert p._api_base == "https://my-proxy.example.com"
    assert p._timeout_seconds == 60.0
    assert p._max_retries == 5


def test_from_llm_config_strips_trailing_slash_from_api_base() -> None:
    """AnthropicLLMProvider.__init__ strips trailing slashes from api_base."""
    p = AnthropicLLMProvider.from_llm_config({"api_base": "https://api.example.com/"})
    assert not p._api_base.endswith("/")


def test_from_llm_config_falls_back_to_default_api_base_when_blank() -> None:
    """from_llm_config uses the default base URL when api_base is empty/whitespace."""
    p = AnthropicLLMProvider.from_llm_config({"api_base": "   "})
    assert p._api_base == DEFAULT_ANTHROPIC_API_BASE


# ---------------------------------------------------------------------------
# AnthropicLLMProvider.complete
# ---------------------------------------------------------------------------


def test_complete_returns_stripped_text_on_success() -> None:
    """complete returns the LLM text stripped of leading/trailing whitespace."""
    response_data = {
        "content": [{"type": "text", "text": "  Answer here.  "}]
    }
    with (
        patch("app.llm.anthropic_llm._anthropic_api_key", return_value="test-key"),
        patch(
            "app.llm.anthropic_llm.request_json_with_retries",
            return_value=response_data,
        ),
    ):
        p = AnthropicLLMProvider("claude-3-5-sonnet-20241022")
        result = p.complete("prompt")
    assert result == "Answer here."


def test_complete_sends_temperature_when_given() -> None:
    """complete includes temperature in the request body when specified."""
    response_data = {"content": [{"type": "text", "text": "ok"}]}
    with (
        patch("app.llm.anthropic_llm._anthropic_api_key", return_value="test-key"),
        patch(
            "app.llm.anthropic_llm.request_json_with_retries",
            return_value=response_data,
        ) as mock_req,
    ):
        p = AnthropicLLMProvider("claude-3-5-sonnet-20241022")
        p.complete("prompt", temperature=0.5)

    body = mock_req.call_args.kwargs["json_body"]
    assert body["temperature"] == 0.5


def test_complete_omits_temperature_when_none() -> None:
    """complete does not include temperature in the body when temperature=None."""
    response_data = {"content": [{"type": "text", "text": "ok"}]}
    with (
        patch("app.llm.anthropic_llm._anthropic_api_key", return_value="test-key"),
        patch(
            "app.llm.anthropic_llm.request_json_with_retries",
            return_value=response_data,
        ) as mock_req,
    ):
        p = AnthropicLLMProvider("claude-3-5-sonnet-20241022")
        p.complete("prompt", temperature=None)

    body = mock_req.call_args.kwargs["json_body"]
    assert "temperature" not in body


def test_complete_raises_llm_provider_error_on_empty_response() -> None:
    """complete raises LLMProviderError when the API returns no text content."""
    empty_response = {"content": []}
    with (
        patch("app.llm.anthropic_llm._anthropic_api_key", return_value="test-key"),
        patch(
            "app.llm.anthropic_llm.request_json_with_retries",
            return_value=empty_response,
        ),
    ):
        p = AnthropicLLMProvider("claude-3-5-sonnet-20241022")
        with pytest.raises(LLMProviderError, match="Empty response"):
            p.complete("prompt")


def test_complete_raises_llm_provider_error_on_http_error() -> None:
    """complete wraps HTTP errors in LLMProviderError."""
    mock_response = MagicMock()
    mock_response.json.return_value = {"error": {"message": "Rate limit exceeded"}}
    http_err = httpx.HTTPStatusError("429", request=MagicMock(), response=mock_response)

    with (
        patch("app.llm.anthropic_llm._anthropic_api_key", return_value="test-key"),
        patch(
            "app.llm.anthropic_llm.request_json_with_retries",
            side_effect=http_err,
        ),
    ):
        p = AnthropicLLMProvider("claude-3-5-sonnet-20241022")
        with pytest.raises(LLMProviderError, match="Rate limit"):
            p.complete("prompt")


def test_complete_raises_when_api_key_missing() -> None:
    """complete raises LLMProviderError when ANTHROPIC_API_KEY is not set."""
    with patch("app.llm.anthropic_llm._anthropic_api_key", side_effect=LLMProviderError("no key")):
        p = AnthropicLLMProvider("claude-3-5-sonnet-20241022")
        with pytest.raises(LLMProviderError):
            p.complete("prompt")


def test_complete_enforces_min_max_tokens() -> None:
    """complete uses at least 1 for max_tokens regardless of what is passed."""
    response_data = {"content": [{"type": "text", "text": "ok"}]}
    with (
        patch("app.llm.anthropic_llm._anthropic_api_key", return_value="test-key"),
        patch(
            "app.llm.anthropic_llm.request_json_with_retries",
            return_value=response_data,
        ) as mock_req,
    ):
        p = AnthropicLLMProvider("claude-3-5-sonnet-20241022")
        p.complete("prompt", max_tokens=0)

    body = mock_req.call_args.kwargs["json_body"]
    assert body["max_tokens"] >= 1


# ---------------------------------------------------------------------------
# get_provider integration: provider=anthropic
# ---------------------------------------------------------------------------


def test_get_provider_returns_anthropic_provider() -> None:
    """get_provider returns AnthropicLLMProvider when provider=anthropic."""
    from app.llm.provider import get_provider

    config = {
        "llm": {
            "provider": "anthropic",
            "model": "claude-3-5-sonnet-20241022",
        }
    }
    p = get_provider(config)
    assert isinstance(p, AnthropicLLMProvider)
    assert p._model == "claude-3-5-sonnet-20241022"
