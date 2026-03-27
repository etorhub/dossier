"""Tests for GeminiLLMProvider and gemini_common helpers."""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from app.llm.gemini import GeminiLLMProvider
from app.llm.gemini_common import (
    DEFAULT_GEMINI_API_BASE,
    _extract_gemini_text,
    gemini_api_key,
    gemini_embed_content,
    gemini_generate_content,
)
from app.llm.provider import LLMProviderError

# ---------------------------------------------------------------------------
# gemini_api_key
# ---------------------------------------------------------------------------


def test_gemini_api_key_reads_env_variable() -> None:
    """gemini_api_key returns the GEMINI_API_KEY env var when set."""
    with patch.dict(os.environ, {"GEMINI_API_KEY": "mykey123"}):
        assert gemini_api_key() == "mykey123"


def test_gemini_api_key_raises_when_missing() -> None:
    """gemini_api_key raises ValueError when the env var is absent."""
    env = {k: v for k, v in os.environ.items() if k != "GEMINI_API_KEY"}
    with (
        patch.dict(os.environ, env, clear=True),
        pytest.raises(ValueError, match="GEMINI_API_KEY"),
    ):
        gemini_api_key()


# ---------------------------------------------------------------------------
# _extract_gemini_text
# ---------------------------------------------------------------------------


def test_extract_gemini_text_returns_concatenated_parts() -> None:
    """_extract_gemini_text joins text parts from the first candidate."""
    data = {"candidates": [{"content": {"parts": [{"text": "Hello "}, {"text": "world"}]}}]}
    assert _extract_gemini_text(data) == "Hello world"


def test_extract_gemini_text_returns_empty_when_no_candidates() -> None:
    """_extract_gemini_text returns '' when candidates list is empty."""
    assert _extract_gemini_text({"candidates": []}) == ""


def test_extract_gemini_text_returns_empty_when_candidates_missing() -> None:
    """_extract_gemini_text returns '' when 'candidates' key is absent."""
    assert _extract_gemini_text({}) == ""


def test_extract_gemini_text_returns_empty_when_parts_missing() -> None:
    """_extract_gemini_text returns '' when content has no parts."""
    data = {"candidates": [{"content": {}}]}
    assert _extract_gemini_text(data) == ""


def test_extract_gemini_text_skips_parts_without_text_key() -> None:
    """_extract_gemini_text ignores parts that do not have a 'text' key."""
    data = {"candidates": [{"content": {"parts": [{"inline_data": {}}, {"text": "result"}]}}]}
    assert _extract_gemini_text(data) == "result"


# ---------------------------------------------------------------------------
# gemini_generate_content
# ---------------------------------------------------------------------------


def test_gemini_generate_content_builds_correct_url() -> None:
    """gemini_generate_content calls request_json_with_retries with the expected URL."""
    response = {"candidates": [{"content": {"parts": [{"text": "generated text"}]}}]}
    with patch(
        "app.llm.gemini_common.request_json_with_retries", return_value=response
    ) as mock_req:
        gemini_generate_content(
            model="gemini-2.0-flash",
            prompt="test",
            max_output_tokens=100,
            api_key="mykey",
        )

    url_arg = mock_req.call_args.args[1]
    assert "gemini-2.0-flash" in url_arg
    assert "generateContent" in url_arg
    assert "mykey" in url_arg


def test_gemini_generate_content_returns_stripped_text() -> None:
    """gemini_generate_content returns stripped text from the response."""
    response = {"candidates": [{"content": {"parts": [{"text": "  answer  "}]}}]}
    with patch("app.llm.gemini_common.request_json_with_retries", return_value=response):
        result = gemini_generate_content(
            model="gemini-2.0-flash",
            prompt="q",
            max_output_tokens=50,
            api_key="k",
        )
    assert result == "answer"


def test_gemini_generate_content_includes_temperature_when_given() -> None:
    """gemini_generate_content passes temperature to the request body."""
    response = {"candidates": [{"content": {"parts": [{"text": "ok"}]}}]}
    with patch(
        "app.llm.gemini_common.request_json_with_retries", return_value=response
    ) as mock_req:
        gemini_generate_content(
            model="gemini-2.0-flash",
            prompt="q",
            max_output_tokens=50,
            api_key="k",
            temperature=0.7,
        )

    body = mock_req.call_args.kwargs["json_body"]
    assert body["generationConfig"]["temperature"] == 0.7


def test_gemini_generate_content_omits_temperature_when_none() -> None:
    """gemini_generate_content does not include temperature when it is None."""
    response = {"candidates": [{"content": {"parts": [{"text": "ok"}]}}]}
    with patch(
        "app.llm.gemini_common.request_json_with_retries", return_value=response
    ) as mock_req:
        gemini_generate_content(
            model="gemini-2.0-flash",
            prompt="q",
            max_output_tokens=50,
            api_key="k",
            temperature=None,
        )

    body = mock_req.call_args.kwargs["json_body"]
    assert "temperature" not in body["generationConfig"]


# ---------------------------------------------------------------------------
# gemini_embed_content
# ---------------------------------------------------------------------------


def test_gemini_embed_content_returns_float_list() -> None:
    """gemini_embed_content returns a list of floats from the response."""
    response = {"embedding": {"values": [0.1, 0.2, 0.3]}}
    with patch("app.llm.gemini_common.request_json_with_retries", return_value=response):
        result = gemini_embed_content(
            model="text-embedding-004",
            text="hello",
            api_key="k",
        )
    assert result == [0.1, 0.2, 0.3]
    assert all(isinstance(v, float) for v in result)


def test_gemini_embed_content_raises_on_empty_response() -> None:
    """gemini_embed_content raises ValueError when the response has no embedding."""
    with (
        patch("app.llm.gemini_common.request_json_with_retries", return_value={}),
        pytest.raises(ValueError, match="Empty response"),
    ):
        gemini_embed_content(model="text-embedding-004", text="hello", api_key="k")


def test_gemini_embed_content_raises_on_empty_values() -> None:
    """gemini_embed_content raises ValueError when values list is empty."""
    response = {"embedding": {"values": []}}
    with (
        patch("app.llm.gemini_common.request_json_with_retries", return_value=response),
        pytest.raises(ValueError, match="Empty embedding"),
    ):
        gemini_embed_content(model="text-embedding-004", text="hello", api_key="k")


# ---------------------------------------------------------------------------
# GeminiLLMProvider.from_llm_config
# ---------------------------------------------------------------------------


def test_from_llm_config_defaults() -> None:
    """from_llm_config applies sensible defaults."""
    p = GeminiLLMProvider.from_llm_config({})
    assert p._model == "gemini-2.0-flash"
    assert p._api_base == DEFAULT_GEMINI_API_BASE
    assert p._timeout_seconds == 120.0
    assert p._max_retries == 3


def test_from_llm_config_reads_all_fields() -> None:
    """from_llm_config reads model, api_base, timeout, max_retries."""
    cfg = {
        "model": "gemini-pro",
        "api_base": "https://proxy.example.com",
        "timeout_seconds": 30,
        "max_retries": 1,
    }
    p = GeminiLLMProvider.from_llm_config(cfg)
    assert p._model == "gemini-pro"
    assert p._api_base == "https://proxy.example.com"
    assert p._timeout_seconds == 30.0
    assert p._max_retries == 1


# ---------------------------------------------------------------------------
# GeminiLLMProvider.complete
# ---------------------------------------------------------------------------


def test_gemini_provider_complete_returns_text() -> None:
    """GeminiLLMProvider.complete returns the text from the LLM."""
    with (
        patch("app.llm.gemini.gemini_api_key", return_value="mykey"),
        patch(
            "app.llm.gemini.gemini_generate_content",
            return_value="Generated answer.",
        ),
    ):
        p = GeminiLLMProvider("gemini-2.0-flash")
        result = p.complete("prompt")
    assert result == "Generated answer."


def test_gemini_provider_complete_raises_on_empty_response() -> None:
    """GeminiLLMProvider.complete raises LLMProviderError on empty text."""
    with (
        patch("app.llm.gemini.gemini_api_key", return_value="key"),
        patch("app.llm.gemini.gemini_generate_content", return_value=""),
    ):
        p = GeminiLLMProvider("gemini-2.0-flash")
        with pytest.raises(LLMProviderError, match="Empty response"):
            p.complete("prompt")


def test_gemini_provider_complete_wraps_value_error() -> None:
    """GeminiLLMProvider.complete wraps ValueError (e.g. missing API key) in LLMProviderError."""
    with (
        patch("app.llm.gemini.gemini_api_key", side_effect=ValueError("GEMINI_API_KEY is not set")),
    ):
        p = GeminiLLMProvider("gemini-2.0-flash")
        with pytest.raises(LLMProviderError, match="GEMINI_API_KEY"):
            p.complete("prompt")


def test_gemini_provider_complete_wraps_generic_exception() -> None:
    """GeminiLLMProvider.complete wraps unexpected exceptions in LLMProviderError."""
    with (
        patch("app.llm.gemini.gemini_api_key", return_value="key"),
        patch("app.llm.gemini.gemini_generate_content", side_effect=RuntimeError("network")),
    ):
        p = GeminiLLMProvider("gemini-2.0-flash")
        with pytest.raises(LLMProviderError, match="network"):
            p.complete("prompt")


# ---------------------------------------------------------------------------
# get_provider integration: provider=gemini
# ---------------------------------------------------------------------------


def test_get_provider_returns_gemini_provider() -> None:
    """get_provider returns GeminiLLMProvider when provider=gemini."""
    from app.llm.provider import get_provider

    config = {
        "llm": {
            "provider": "gemini",
            "model": "gemini-2.0-flash",
        }
    }
    p = get_provider(config)
    assert isinstance(p, GeminiLLMProvider)
    assert p._model == "gemini-2.0-flash"
