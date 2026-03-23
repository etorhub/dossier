"""Shared HTTP helpers for remote LLM APIs (retries, JSON errors)."""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)


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
