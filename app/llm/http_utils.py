"""Shared HTTP helpers for remote LLM APIs (retries, JSON errors)."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any, TypeVar

import httpx

T = TypeVar("T")

logger = logging.getLogger(__name__)


def is_ollama_connection_failure(exc: BaseException) -> bool:
    """True when the error indicates Ollama cannot be reached (retries won't help)."""
    needles = (
        "failed to connect",
        "connection refused",
        "could not connect",
        "name or service not known",
        "no route to host",
        "network is unreachable",
        "getaddrinfo failed",
    )
    seen: set[int] = set()
    parts: list[str] = []
    stack: list[BaseException | None] = [exc]

    while stack:
        e = stack.pop()
        while e is not None and id(e) not in seen:
            seen.add(id(e))
            parts.append(str(e).lower())
            if e.__cause__ is not None:
                stack.append(e.__cause__)
            e = e.__context__

    blob = " ".join(parts)
    return any(n in blob for n in needles)


def request_json_with_retries(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    json_body: dict[str, Any] | None = None,
    timeout_seconds: float = 120.0,
    max_retries: int = 3,
) -> dict[str, Any]:
    """POST/GET JSON with retries on 429 and 5xx. Raises httpx.HTTPStatusError on final failure."""
    headers = headers or {}
    last_error: Exception | None = None
    for attempt in range(max(max_retries, 1)):
        try:
            with httpx.Client(timeout=timeout_seconds) as client:
                response = client.request(
                    method,
                    url,
                    headers=headers,
                    json=json_body,
                )
            if response.status_code == 429 or response.status_code >= 500:
                last_error = httpx.HTTPStatusError(
                    f"HTTP {response.status_code}",
                    request=response.request,
                    response=response,
                )
                wait = min(2.0**attempt, 30.0)
                logger.warning(
                    "HTTP %s for %s (attempt %s/%s), retrying in %.1fs",
                    response.status_code,
                    url.split("?", 1)[0],
                    attempt + 1,
                    max_retries,
                    wait,
                )
                time.sleep(wait)
                continue
            response.raise_for_status()
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError("Expected JSON object in response")
            return data
        except (httpx.TimeoutException, httpx.TransportError) as e:
            last_error = e
            wait = min(2.0**attempt, 30.0)
            logger.warning(
                "Request error for %s (attempt %s/%s): %s; retrying in %.1fs",
                url.split("?", 1)[0],
                attempt + 1,
                max_retries,
                e,
                wait,
            )
            time.sleep(wait)
    if last_error:
        raise last_error
    raise RuntimeError("request_json_with_retries: no attempts made")


def run_with_retries(
    fn: Callable[[], T],
    *,
    max_retries: int = 3,
    label: str = "LLM call",
    retry_if: Callable[[Exception], bool] | None = None,
) -> T:
    """Run a callable with exponential backoff (same cap as HTTP retries).

    If retry_if is set and returns False for an exception, that exception is
    raised immediately (no further attempts, no sleep).
    """
    last_error: Exception | None = None
    n = max(max_retries, 1)
    for attempt in range(n):
        try:
            return fn()
        except Exception as e:
            last_error = e
            if retry_if is not None and not retry_if(e):
                raise e
            if attempt + 1 >= n:
                break
            wait = min(2.0**attempt, 30.0)
            logger.warning(
                "%s failed (attempt %s/%s): %s; retrying in %.1fs",
                label,
                attempt + 1,
                n,
                e,
                wait,
            )
            time.sleep(wait)
    assert last_error is not None
    raise last_error
