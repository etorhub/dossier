"""LLM provider abstraction. Use get_provider(); never call SDKs from routes."""

import logging
import os
from abc import ABC, abstractmethod
from typing import Any

from app.config import load_config
from app.llm.http_utils import is_ollama_connection_failure, run_with_retries

logger = logging.getLogger(__name__)


class LLMProviderError(Exception):
    """Raised when an LLM provider call fails."""


class LLMProvider(ABC):
    """Abstract base for LLM providers."""

    def warm_up(self) -> None:  # noqa: B027
        """Pre-load resources before parallel use. No-op for Ollama."""
        pass

    @abstractmethod
    def complete(
        self,
        prompt: str,
        max_tokens: int = 1000,
        *,
        temperature: float | None = None,
    ) -> str:
        """Send prompt to the model and return the generated text.

        temperature: optional sampling temperature; when None, provider default applies.
        """
        ...


class OllamaProvider(LLMProvider):
    """LLM via Ollama. No API key required. Runs locally or in a dedicated container."""

    def __init__(
        self,
        model: str,
        host: str = "http://ollama:11434",
        *,
        max_retries: int = 3,
        timeout: float | None = None,
    ) -> None:
        self._model = model
        self._host = host
        self._max_retries = max_retries
        self._timeout = timeout

    def _complete_once(
        self, prompt: str, max_tokens: int, temperature: float | None
    ) -> str:
        import ollama

        try:
            client = ollama.Client(host=self._host, timeout=self._timeout)
            options: dict[str, Any] = {"num_predict": max_tokens}
            if temperature is not None:
                options["temperature"] = float(temperature)
            response = client.chat(
                model=self._model,
                messages=[{"role": "user", "content": prompt}],
                options=options,
            )
            message = (
                response.get("message")
                if isinstance(response, dict)
                else getattr(response, "message", None)
            )
            if not message:
                raise LLMProviderError("Empty response from Ollama")
            content = (
                message.get("content")
                if isinstance(message, dict)
                else getattr(message, "content", None)
            )
            if content is None:
                raise LLMProviderError("Empty response from Ollama")
            return str(content).strip()
        except Exception as e:
            if isinstance(e, LLMProviderError):
                raise
            raise LLMProviderError(str(e)) from e

    def complete(
        self,
        prompt: str,
        max_tokens: int = 1000,
        *,
        temperature: float | None = None,
    ) -> str:
        return run_with_retries(
            lambda: self._complete_once(prompt, max_tokens, temperature),
            max_retries=self._max_retries,
            label=f"Ollama chat ({self._model})",
            retry_if=lambda exc: not is_ollama_connection_failure(exc),
        )


def get_provider(
    config: dict[str, Any] | None = None,
    task: str | None = None,
) -> LLMProvider:
    """Return the configured LLM provider (Ollama, Gemini, Anthropic, or vLLM-compatible).

    task: optional task name ('rewrite', 'simplify', 'translate').
    Uses llm.{task}_model if set, otherwise falls back to llm.model.
    """
    if config is None:
        config = load_config()
    llm = config.get("llm", {})
    provider_name = (llm.get("provider") or "ollama").lower()
    fallback_model = llm.get("model") or "qwen2.5:7b"
    if task:
        model = llm.get(f"{task}_model") or fallback_model
    else:
        model = fallback_model

    if provider_name == "ollama":
        host = llm.get("host") or os.environ.get("OLLAMA_HOST") or "http://ollama:11434"
        retries = int(llm.get("max_retries") or 3)
        raw_timeout = llm.get("request_timeout_seconds")
        timeout = float(raw_timeout) if raw_timeout is not None else None
        return OllamaProvider(model=model, host=host, max_retries=retries, timeout=timeout)
    if provider_name == "gemini":
        from app.llm.gemini import GeminiLLMProvider

        cfg = {**llm, "model": model}
        return GeminiLLMProvider.from_llm_config(cfg)
    if provider_name == "anthropic":
        from app.llm.anthropic_llm import AnthropicLLMProvider

        cfg = {**llm, "model": model}
        return AnthropicLLMProvider.from_llm_config(cfg)
    if provider_name == "vllm":
        from app.llm.vllm_provider import VllmOpenAIProvider

        cfg = {**llm, "model": model}
        return VllmOpenAIProvider.from_llm_config(cfg)
    raise LLMProviderError(f"Unknown llm.provider: {provider_name!r}")
