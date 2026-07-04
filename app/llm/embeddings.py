"""Embedding provider abstraction. Used for article clustering."""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from typing import Any

from app.config import load_config
from app.llm.http_utils import is_ollama_connection_failure, run_with_retries


class EmbeddingProviderError(Exception):
    """Raised when an embedding API call fails."""


def _ollama_embed_error_is_retryable(exc: Exception) -> bool:
    return not is_ollama_connection_failure(exc)


class EmbeddingProvider(ABC):
    """Abstract base for embedding providers."""

    @abstractmethod
    def embed(self, text: str) -> list[float]:
        """Embed text and return a vector of floats."""
        ...


class GeminiEmbeddingProvider(EmbeddingProvider):
    """Embeddings via Google Gemini embedContent (requires GEMINI_API_KEY)."""

    def __init__(
        self,
        model: str = "text-embedding-004",
        *,
        api_base: str | None = None,
        timeout_seconds: float = 60.0,
        max_retries: int = 3,
        max_chars: int = 8000,
    ) -> None:
        from app.llm.gemini_common import DEFAULT_GEMINI_API_BASE

        self._model = model
        self._api_base = (api_base or DEFAULT_GEMINI_API_BASE).rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._max_retries = max_retries
        self._max_chars = max_chars

    @classmethod
    def from_embeddings_config(cls, embeddings_cfg: dict[str, Any]) -> GeminiEmbeddingProvider:
        from app.llm.gemini_common import DEFAULT_EMBED_MODEL, DEFAULT_GEMINI_API_BASE

        model = embeddings_cfg.get("model") or DEFAULT_EMBED_MODEL
        raw_base = embeddings_cfg.get("api_base")
        api_base = (
            raw_base if isinstance(raw_base, str) and raw_base.strip() else DEFAULT_GEMINI_API_BASE
        )
        timeout = float(embeddings_cfg.get("timeout_seconds") or 60.0)
        retries = int(embeddings_cfg.get("max_retries") or 3)
        max_chars = int(embeddings_cfg.get("max_input_chars") or 8000)
        return cls(
            model=model,
            api_base=api_base,
            timeout_seconds=timeout,
            max_retries=retries,
            max_chars=max_chars,
        )

    def embed(self, text: str) -> list[float]:
        from app.llm.gemini_common import gemini_api_key, gemini_embed_content

        truncated = text[: self._max_chars]
        try:
            key = gemini_api_key()
            return gemini_embed_content(
                model=self._model,
                text=truncated,
                api_key=key,
                api_base=self._api_base,
                timeout_seconds=self._timeout_seconds,
                max_retries=self._max_retries,
            )
        except ValueError as e:
            raise EmbeddingProviderError(str(e)) from e
        except Exception as e:
            if isinstance(e, EmbeddingProviderError):
                raise
            raise EmbeddingProviderError(str(e)) from e


class VllmOpenAIEmbeddingProvider(EmbeddingProvider):
    """Embeddings via POST {api_base}/embeddings (OpenAI-compatible, e.g. Modal vLLM)."""

    def __init__(
        self,
        model: str,
        api_base: str,
        *,
        api_key: str | None = None,
        timeout_seconds: float = 60.0,
        max_retries: int = 3,
        max_chars: int = 8000,
    ) -> None:
        self._model = model
        self._api_base = api_base.rstrip("/")
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds
        self._max_retries = max_retries
        self._max_chars = max_chars

    @classmethod
    def from_embeddings_config(cls, embeddings_cfg: dict[str, Any]) -> VllmOpenAIEmbeddingProvider:
        model = embeddings_cfg.get("model") or "BAAI/bge-m3"
        raw_base = embeddings_cfg.get("api_base")
        if isinstance(raw_base, str) and raw_base.strip():
            api_base = raw_base.strip()
        else:
            api_base = "http://127.0.0.1:8000/v1"
        timeout = float(embeddings_cfg.get("timeout_seconds") or 60.0)
        retries = int(embeddings_cfg.get("max_retries") or 3)
        max_chars = int(embeddings_cfg.get("max_input_chars") or 8000)
        key = embeddings_cfg.get("api_key")
        if isinstance(key, str) and key.strip():
            api_key: str | None = key.strip()
        else:
            api_key = os.environ.get("EMBED_API_KEY") or None
            if api_key is not None and not api_key.strip():
                api_key = None
        return cls(
            model=model,
            api_base=api_base,
            api_key=api_key,
            timeout_seconds=timeout,
            max_retries=retries,
            max_chars=max_chars,
        )

    def embed(self, text: str) -> list[float]:
        from app.llm.http_utils import request_json_with_retries

        url = f"{self._api_base}/embeddings"
        headers: dict[str, str] = {}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        body = {
            "model": self._model,
            "input": text[: self._max_chars],
        }
        try:
            data = request_json_with_retries(
                "POST",
                url,
                headers=headers,
                json_body=body,
                timeout_seconds=self._timeout_seconds,
                max_retries=self._max_retries,
            )
        except Exception as e:
            if isinstance(e, EmbeddingProviderError):
                raise
            raise EmbeddingProviderError(str(e)) from e
        rows = data.get("data")
        if not isinstance(rows, list) or not rows:
            raise EmbeddingProviderError("Embeddings response has no data")
        first = rows[0]
        if not isinstance(first, dict):
            raise EmbeddingProviderError("Invalid embedding row in response")
        embedding = first.get("embedding")
        if not isinstance(embedding, list) or not embedding:
            raise EmbeddingProviderError("Empty embedding vector in response")
        return [float(x) for x in embedding]


class OllamaEmbeddingProvider(EmbeddingProvider):
    """Embeddings via Ollama. No API key. Runs locally or in a dedicated container."""

    def __init__(
        self,
        model: str = "paraphrase-multilingual",
        host: str = "http://ollama:11434",
        *,
        max_retries: int = 3,
        max_input_chars: int = 8000,
    ) -> None:
        self._model = model
        self._host = host
        self._max_retries = max_retries
        self._max_input_chars = max_input_chars

    def _embed_once(self, text: str) -> list[float]:
        import ollama

        try:
            client = ollama.Client(host=self._host)
            response = client.embed(model=self._model, input=text[: self._max_input_chars])
            embeddings = (
                response.get("embeddings")
                if isinstance(response, dict)
                else getattr(response, "embeddings", None)
            )
            if not embeddings:
                raise EmbeddingProviderError("Empty response from Ollama embeddings")
            return list(embeddings[0])
        except Exception as e:
            if isinstance(e, EmbeddingProviderError):
                raise
            raise EmbeddingProviderError(str(e)) from e

    def embed(self, text: str) -> list[float]:
        return run_with_retries(
            lambda: self._embed_once(text),
            max_retries=self._max_retries,
            label=f"Ollama embed ({self._model})",
            retry_if=_ollama_embed_error_is_retryable,
        )


def get_embedding_provider(config: dict[str, Any] | None = None) -> EmbeddingProvider:
    """Return the configured embedding provider (Ollama, Gemini, or vLLM-compatible)."""
    cfg = config or load_config()
    embeddings_cfg = cfg.get("embeddings", {})
    provider_name = (embeddings_cfg.get("provider") or "ollama").lower()
    if provider_name == "vllm":
        return VllmOpenAIEmbeddingProvider.from_embeddings_config(embeddings_cfg)
    if provider_name == "ollama":
        model = embeddings_cfg.get("model") or "paraphrase-multilingual"
        host = embeddings_cfg.get("host") or os.environ.get("OLLAMA_HOST") or "http://ollama:11434"
        retries = int(embeddings_cfg.get("max_retries") or 3)
        max_chars = int(embeddings_cfg.get("max_input_chars") or 8000)
        return OllamaEmbeddingProvider(
            model=model,
            host=host,
            max_retries=retries,
            max_input_chars=max_chars,
        )
    if provider_name == "gemini":
        return GeminiEmbeddingProvider.from_embeddings_config(embeddings_cfg)
    raise EmbeddingProviderError(f"Unknown embeddings.provider: {provider_name!r}")
