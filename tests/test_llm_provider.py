"""Tests for LLM provider layer."""

import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from app.llm.provider import (
    LLMProviderError,
    OllamaProvider,
    get_provider,
)
from app.llm.vllm_provider import VllmOpenAIProvider


def test_get_provider_ollama() -> None:
    """get_provider returns OllamaProvider for ollama config."""
    config = {"llm": {"provider": "ollama", "model": "qwen2.5:7b"}}
    provider = get_provider(config)
    assert isinstance(provider, OllamaProvider)
    assert provider._model == "qwen2.5:7b"
    assert provider._host == "http://ollama:11434"
    assert provider._max_retries == 3
    assert provider._timeout == 300.0


def test_get_provider_ollama_with_host() -> None:
    """get_provider uses host from config when set."""
    config = {"llm": {"model": "qwen2.5:7b", "host": "http://localhost:11434"}}
    provider = get_provider(config)
    assert isinstance(provider, OllamaProvider)
    assert provider._host == "http://localhost:11434"


def test_get_provider_vllm() -> None:
    """get_provider returns VllmOpenAIProvider when llm.provider is vllm."""
    config = {
        "llm": {
            "provider": "vllm",
            "model": "Qwen/Qwen2.5-7B-Instruct",
            "api_base": "http://localhost:8000/v1",
        }
    }
    provider = get_provider(config)
    assert isinstance(provider, VllmOpenAIProvider)
    assert provider._model == "Qwen/Qwen2.5-7B-Instruct"
    assert provider._api_base == "http://localhost:8000/v1"


def test_vllm_provider_complete() -> None:
    """VllmOpenAIProvider.complete parses OpenAI-style JSON."""
    payload = {
        "choices": [
            {"message": {"content": "TITLE:\nT\n\nSUMMARY:\nOne. Two. Three.\n\nFULL:\nF."}}
        ]
    }
    with patch("app.llm.vllm_provider.request_json_with_retries", return_value=payload):
        p = VllmOpenAIProvider("m", "http://x:1/v1", max_retries=1)
        out = p.complete("hi", max_tokens=100)
    assert "TITLE:" in out


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


def test_ollama_provider_complete_passes_temperature() -> None:
    """OllamaProvider.complete forwards temperature in options when set."""
    mock_response = {
        "message": {"content": "TITLE:\nT\n\nSUMMARY:\nS.\n\nFULL:\nF."}
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
        provider.complete("Hi", max_tokens=50, temperature=0.15)

    mock_client.chat.assert_called_once_with(
        model="qwen2.5:7b",
        messages=[{"role": "user", "content": "Hi"}],
        options={"num_predict": 50, "temperature": 0.15},
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


def test_ollama_provider_unreachable_fails_fast_without_retries() -> None:
    """Unreachable Ollama does not burn multiple retries per call."""
    mock_client = MagicMock()
    mock_client.chat.side_effect = Exception(
        "Failed to connect to Ollama. Please check that Ollama is downloaded"
    )

    with (
        patch("ollama.Client") as mock_client_class,
        patch("app.llm.http_utils.time.sleep") as mock_sleep,
    ):
        mock_client_class.return_value = mock_client
        provider = OllamaProvider(model="qwen2.5:7b", max_retries=3)
        with pytest.raises(LLMProviderError):
            provider.complete("Hello")

    mock_client.chat.assert_called_once()
    mock_sleep.assert_not_called()


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


def test_ollama_provider_serializes_concurrent_complete() -> None:
    """Concurrent complete() calls do not overlap (stable VRAM on single-GPU Ollama)."""
    concurrent = {"n": 0, "max": 0}
    counter_lock = threading.Lock()
    ok_body = {"message": {"content": "TITLE:\nT\n\nSUMMARY:\nS.\n\nFULL:\nF."}}

    def chat_side_effect(*_a: object, **_kw: object) -> dict[str, object]:
        with counter_lock:
            concurrent["n"] += 1
            concurrent["max"] = max(concurrent["max"], concurrent["n"])
        try:
            time.sleep(0.06)
            return ok_body
        finally:
            with counter_lock:
                concurrent["n"] -= 1

    mock_client = MagicMock()
    mock_client.chat.side_effect = chat_side_effect

    with patch("ollama.Client") as mock_client_class:
        mock_client_class.return_value = mock_client
        provider = OllamaProvider(model="qwen2.5:7b", max_retries=1)
        t1 = threading.Thread(target=lambda: provider.complete("a", max_tokens=10))
        t2 = threading.Thread(target=lambda: provider.complete("b", max_tokens=10))
        t1.start()
        t2.start()
        t1.join()
        t2.join()

    assert concurrent["max"] == 1
