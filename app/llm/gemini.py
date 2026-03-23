"""Google Gemini (Generative Language API) LLM provider."""

from __future__ import annotations

from typing import Any

from app.llm.gemini_common import (
    DEFAULT_GEMINI_API_BASE,
    gemini_api_key,
    gemini_generate_content,
)
from app.llm.provider import LLMProvider, LLMProviderError


class GeminiLLMProvider(LLMProvider):
    """Text generation via Gemini generateContent (Google AI / API key)."""

    def __init__(
        self,
        model: str,
        *,
        api_base: str = DEFAULT_GEMINI_API_BASE,
        timeout_seconds: float = 120.0,
        max_retries: int = 3,
    ) -> None:
        self._model = model
        self._api_base = api_base.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._max_retries = max_retries

    @classmethod
    def from_llm_config(cls, llm: dict[str, Any]) -> GeminiLLMProvider:
        model = llm.get("model") or "gemini-2.0-flash"
        raw_base = llm.get("api_base")
        api_base = (
            raw_base if isinstance(raw_base, str) and raw_base.strip() else DEFAULT_GEMINI_API_BASE
        )
        timeout = float(llm.get("timeout_seconds") or 120.0)
        retries = int(llm.get("max_retries") or 3)
        return cls(
            model,
            api_base=api_base,
            timeout_seconds=timeout,
            max_retries=retries,
        )

    def complete(self, prompt: str, max_tokens: int = 1000) -> str:
        try:
            key = gemini_api_key()
            text = gemini_generate_content(
                model=self._model,
                prompt=prompt,
                max_output_tokens=max_tokens,
                api_key=key,
                api_base=self._api_base,
                timeout_seconds=self._timeout_seconds,
                max_retries=self._max_retries,
            )
        except ValueError as e:
            raise LLMProviderError(str(e)) from e
        except Exception as e:
            if isinstance(e, LLMProviderError):
                raise
            raise LLMProviderError(str(e)) from e
        if not text:
            raise LLMProviderError("Empty response from Gemini")
        return text
