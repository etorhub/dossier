"""Anthropic Claude Messages API LLM provider."""

from __future__ import annotations

import os
from typing import Any

import httpx

from app.llm.http_utils import request_json_with_retries
from app.llm.provider import LLMProvider, LLMProviderError

DEFAULT_ANTHROPIC_API_BASE = "https://api.anthropic.com"
ANTHROPIC_VERSION = "2023-06-01"


def _anthropic_api_key() -> str:
    key = (os.environ.get("ANTHROPIC_API_KEY") or "").strip()
    if not key:
        raise LLMProviderError("ANTHROPIC_API_KEY is not set")
    return key


class AnthropicLLMProvider(LLMProvider):
    """Text generation via Claude Messages API."""

    def __init__(
        self,
        model: str,
        *,
        api_base: str = DEFAULT_ANTHROPIC_API_BASE,
        timeout_seconds: float = 120.0,
        max_retries: int = 3,
    ) -> None:
        self._model = model
        self._api_base = api_base.rstrip("/")
        self._timeout_seconds = timeout_seconds
        self._max_retries = max_retries

    @classmethod
    def from_llm_config(cls, llm: dict[str, Any]) -> AnthropicLLMProvider:
        model = llm.get("model") or "claude-3-5-sonnet-20241022"
        raw_base = llm.get("api_base")
        api_base = (
            raw_base
            if isinstance(raw_base, str) and raw_base.strip()
            else DEFAULT_ANTHROPIC_API_BASE
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
        api_key = _anthropic_api_key()
        url = f"{self._api_base}/v1/messages"
        # Anthropic requires max_tokens >= 1; cap to API limits in config
        mt = max(1, int(max_tokens))
        body: dict[str, Any] = {
            "model": self._model,
            "max_tokens": mt,
            "messages": [{"role": "user", "content": prompt}],
        }
        headers = {
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": ANTHROPIC_VERSION,
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
        except httpx.HTTPStatusError as e:
            detail = ""
            try:
                err_json = e.response.json()
                if isinstance(err_json, dict) and err_json.get("error"):
                    err = err_json["error"]
                    if isinstance(err, dict):
                        detail = str(err.get("message", err))
                    else:
                        detail = str(err)
            except Exception:
                detail = e.response.text[:500]
            raise LLMProviderError(detail or str(e)) from e
        except Exception as e:
            if isinstance(e, LLMProviderError):
                raise
            raise LLMProviderError(str(e)) from e

        text = _extract_anthropic_text(data)
        if not text:
            raise LLMProviderError("Empty response from Anthropic")
        return text.strip()


def _extract_anthropic_text(data: dict[str, Any]) -> str:
    content = data.get("content")
    if not isinstance(content, list):
        return ""
    parts: list[str] = []
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            t = block.get("text")
            if t:
                parts.append(str(t))
    return "".join(parts)
