"""Shared Gemini API helpers (auth, HTTP) for LLM and embeddings."""

from __future__ import annotations

import os
import urllib.parse
from typing import Any

from app.llm.http_utils import request_json_with_retries

DEFAULT_GEMINI_API_BASE = "https://generativelanguage.googleapis.com"
DEFAULT_EMBED_MODEL = "text-embedding-004"


def gemini_api_key() -> str:
    key = (os.environ.get("GEMINI_API_KEY") or "").strip()
    if not key:
        raise ValueError("GEMINI_API_KEY is not set")
    return key


def gemini_generate_content(
    *,
    model: str,
    prompt: str,
    max_output_tokens: int,
    api_key: str,
    api_base: str = DEFAULT_GEMINI_API_BASE,
    timeout_seconds: float = 120.0,
    max_retries: int = 3,
    temperature: float | None = None,
    system: str | None = None,
) -> str:
    """Call generateContent; return concatenated text from candidates."""
    base = api_base.rstrip("/")
    model_path = model.removeprefix("models/")
    q = urllib.parse.urlencode({"key": api_key})
    url = f"{base}/v1beta/models/{model_path}:generateContent?{q}"
    gen_cfg: dict[str, Any] = {
        "maxOutputTokens": max_output_tokens,
    }
    if temperature is not None:
        gen_cfg["temperature"] = float(temperature)
    body: dict[str, Any] = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": gen_cfg,
    }
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}
    data = request_json_with_retries(
        "POST",
        url,
        json_body=body,
        headers={"Content-Type": "application/json"},
        timeout_seconds=timeout_seconds,
        max_retries=max_retries,
    )
    return _extract_gemini_text(data).strip()


def gemini_embed_content(
    *,
    model: str,
    text: str,
    api_key: str,
    api_base: str = DEFAULT_GEMINI_API_BASE,
    timeout_seconds: float = 60.0,
    max_retries: int = 3,
) -> list[float]:
    """Call embedContent; return embedding values."""
    base = api_base.rstrip("/")
    model_path = model.removeprefix("models/")
    q = urllib.parse.urlencode({"key": api_key})
    url = f"{base}/v1beta/models/{model_path}:embedContent?{q}"
    body = {
        "model": f"models/{model_path}",
        "content": {"parts": [{"text": text}]},
    }
    data = request_json_with_retries(
        "POST",
        url,
        json_body=body,
        headers={"Content-Type": "application/json"},
        timeout_seconds=timeout_seconds,
        max_retries=max_retries,
    )
    emb = data.get("embedding")
    if not isinstance(emb, dict):
        raise ValueError("Empty response from Gemini embeddings")
    values = emb.get("values")
    if not isinstance(values, list) or not values:
        raise ValueError("Empty embedding vector from Gemini")
    return [float(x) for x in values]


def _extract_gemini_text(data: dict[str, Any]) -> str:
    candidates = data.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        return ""
    first = candidates[0]
    if not isinstance(first, dict):
        return ""
    content = first.get("content")
    if not isinstance(content, dict):
        return ""
    parts = content.get("parts")
    if not isinstance(parts, list):
        return ""
    chunks: list[str] = []
    for p in parts:
        if isinstance(p, dict) and p.get("text"):
            chunks.append(str(p["text"]))
    return "".join(chunks)
