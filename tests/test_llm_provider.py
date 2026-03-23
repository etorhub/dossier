"""Tests for LLM provider layer."""

from unittest.mock import MagicMock, patch

import pytest

from app.llm.provider import (
    LLMProviderError,
    OllamaProvider,
    get_provider,
)


def test_get_provider_ollama() -> None:
    """get_provider returns OllamaProvider for ollama config."""
    config = {"llm": {"provider": "ollama", "model": "qwen2.5:7b"}}
    provider = get_provider(config)
    assert isinstance(provider, OllamaProvider)
    assert provider._model == "qwen2.5:7b"
    assert provider._host == "http://ollama:11434"
    assert provider._max_retries == 3


def test_get_provider_ollama_with_host() -> None:
    """get_provider uses host from config when set."""
    config = {"llm": {"model": "qwen2.5:7b", "host": "http://localhost:11434"}}
    provider = get_provider(config)
    assert isinstance(provider, OllamaProvider)
    assert provider._host == "http://localhost:11434"


def test_get_provider_defaults() -> None:
    """get_provider uses defaults when config minimal."""
    config = {}
    provider = get_provider(config)
    assert isinstance(provider, OllamaProvider)
    assert provider._model == "qwen2.5:7b"
    assert provider._host == "http://ollama:11434"


def test_ollama_provider_complete() -> None:
    """OllamaProvider.complete returns content from mocked client."""
    mock_response = {
        "message": {"content": "TITLE:\nTest\n\nSUMMARY:\nOne. Two.\n\nFULL:\nText."}
    }
    mock_client = MagicMock()
    mock_client.chat.return_value = mock_response

    with patch("ollama.Client") as mock_client_class:
        mock_client_class.return_value = mock_client
        provider = OllamaProvider(
            model="qwen2.5:7b",
            host="http://localhost:11434",
            max_retries=1,
        )
        result = provider.complete("Rewrite this", max_tokens=100)

    assert result == "TITLE:\nTest\n\nSUMMARY:\nOne. Two.\n\nFULL:\nText."
    mock_client.chat.assert_called_once_with(
        model="qwen2.5:7b",
        messages=[{"role": "user", "content": "Rewrite this"}],
        options={"num_predict": 100},
    )


def test_ollama_provider_raises_on_empty_response() -> None:
    """OllamaProvider.complete raises LLMProviderError when response has no content."""
    mock_client = MagicMock()
    mock_client.chat.return_value = {"message": {}}

    with patch("ollama.Client") as mock_client_class:
        mock_client_class.return_value = mock_client
        provider = OllamaProvider(model="qwen2.5:7b", max_retries=1)
        with pytest.raises(LLMProviderError, match="Empty response"):
            provider.complete("Hello")


def test_ollama_provider_raises_on_error() -> None:
    """OllamaProvider.complete raises LLMProviderError on client failure."""
    mock_client = MagicMock()
    mock_client.chat.side_effect = Exception("Connection refused")

    with patch("ollama.Client") as mock_client_class:
        mock_client_class.return_value = mock_client
        provider = OllamaProvider(model="qwen2.5:7b", max_retries=1)
        with pytest.raises(LLMProviderError, match="Connection refused"):
            provider.complete("Hello")


def test_ollama_provider_retries_then_succeeds() -> None:
    """OllamaProvider.complete retries transient failures up to max_retries."""
    mock_response = {
        "message": {"content": "TITLE:\nOk\n\nSUMMARY:\nS.\n\nFULL:\nF."}
    }
    mock_client = MagicMock()
    mock_client.chat.side_effect = [
        Exception("busy"),
        mock_response,
    ]

    with (
        patch("ollama.Client") as mock_client_class,
        patch("app.llm.http_utils.time.sleep"),
    ):
        mock_client_class.return_value = mock_client
        provider = OllamaProvider(model="qwen2.5:7b", max_retries=3)
        result = provider.complete("Hi", max_tokens=50)

    assert "Ok" in result
    assert mock_client.chat.call_count == 2


def test_ollama_provider_warm_up_noop() -> None:
    """OllamaProvider.warm_up is a no-op (Ollama handles loading)."""
    provider = OllamaProvider(model="qwen2.5:7b")
    provider.warm_up()  # Should not raise
