"""OpenAI-compatible chat HTTP API (vLLM, SGLang, LocalAI, etc.)."""

from __future__ import annotations

import os
from typing import Any

from app.llm.http_utils import request_json_with_retries
from app.llm.provider import LLMProvider, LLMProviderError


def _extract_chat_content(data: dict[str, Any]) -> str:
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        raise LLMProviderError("Chat completion response has no choices")
    first = choices[0]
    if not isinstance(first, dict):
        raise LLMProviderError("Invalid choice in chat completion response")
    msg = first.get("message")
    if not isinstance(msg, dict):
        raise LLMProviderError("Chat completion missing message")
    content = msg.get("content")
    if content is None:
        raise LLMProviderError("Empty message content in chat completion")
    return str(content).strip()


class VllmOpenAIProvider(LLMProvider):
    """LLM via POST {api_base}/chat/completions (OpenAI-compatible)."""

    def __init__(
        self,
        model: str,
        api_base: str,
        *,
        api_key: str | None = None,
        timeout_seconds: float = 300.0,
        max_retries: int = 3,
    ) -> None:
        self._model = model
        base = api_base.rstrip("/")
        self._api_base = base
        self._api_key = api_key
        self._timeout_seconds = timeout_seconds
        self._max_retries = max_retries

    @classmethod
    def from_llm_config(cls, llm: dict[str, Any]) -> VllmOpenAIProvider:
        model = llm.get("model") or "Qwen/Qwen2.5-7B-Instruct"
        raw_base = llm.get("api_base")
        if isinstance(raw_base, str) and raw_base.strip():
            api_base = raw_base.strip()
        else:
            api_base = "http://127.0.0.1:8000/v1"
        timeout = float(llm.get("timeout_seconds") or 300.0)
        retries = int(llm.get("max_retries") or 3)
        key = llm.get("api_key")
        if isinstance(key, str) and key.strip():
            api_key: str | None = key.strip()
        else:
            api_key = os.environ.get("OPENAI_API_KEY") or None
            if api_key is not None and not api_key.strip():
                api_key = None
        return cls(
            model,
            api_base,
            api_key=api_key,
            timeout_seconds=timeout,
            max_retries=retries,
        )

    def complete(
        self,
        prompt: str,
        max_tokens: int = 1000,
        *,
        temperature: float | None = None,
        system: str | None = None,
    ) -> str:
        url = f"{self._api_base}/chat/completions"
        headers: dict[str, str] = {}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        messages: list[dict[str, str]] = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        body: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "max_tokens": max_tokens,
        }
        if temperature is not None:
            body["temperature"] = float(temperature)
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
            if isinstance(e, LLMProviderError):
                raise
            raise LLMProviderError(str(e)) from e
        return _extract_chat_content(data)
