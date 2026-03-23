"""Tests for shared HTTP / retry helpers."""

from unittest.mock import patch

import pytest

from app.llm.http_utils import is_ollama_connection_failure, run_with_retries


def test_run_with_retries_first_call_ok() -> None:
    """run_with_retries returns immediately on success."""
    calls = 0

    def fn() -> int:
        nonlocal calls
        calls += 1
        return 42

    assert run_with_retries(fn, max_retries=3, label="test") == 42
    assert calls == 1


def test_run_with_retries_succeeds_after_transient_failure() -> None:
    """run_with_retries retries and returns when a later attempt succeeds."""
    attempts = 0

    def fn() -> str:
        nonlocal attempts
        attempts += 1
        if attempts < 2:
            raise RuntimeError("transient overload")
        return "ok"

    with patch("app.llm.http_utils.time.sleep"):
        assert run_with_retries(fn, max_retries=3, label="test") == "ok"
    assert attempts == 2


def test_run_with_retries_retry_if_false_raises_immediately() -> None:
    """When retry_if returns False, no sleep and no further attempts."""

    def fn() -> None:
        raise ValueError("fatal")

    with patch("app.llm.http_utils.time.sleep") as mock_sleep:
        with pytest.raises(ValueError, match="fatal"):
            run_with_retries(
                fn,
                max_retries=3,
                label="test",
                retry_if=lambda e: False,
            )
    mock_sleep.assert_not_called()


def test_is_ollama_connection_failure_message() -> None:
    """Detect typical Ollama client unreachable errors."""
    assert is_ollama_connection_failure(
        Exception("Failed to connect to Ollama. Please check that Ollama is downloaded")
    )
    assert is_ollama_connection_failure(Exception("connection refused"))
    assert not is_ollama_connection_failure(Exception("model not found"))


def test_run_with_retries_raises_after_exhausted() -> None:
    """run_with_retries raises the last error after max_retries attempts."""

    def fail() -> None:
        raise RuntimeError("always fails")

    with patch("app.llm.http_utils.time.sleep"):
        with pytest.raises(RuntimeError, match="always fails"):
            run_with_retries(fail, max_retries=2, label="test")


def test_run_with_retries_at_least_one_attempt() -> None:
    """max_retries below 1 is treated as 1."""

    def fail() -> None:
        raise ValueError("nope")

    with patch("app.llm.http_utils.time.sleep"):
        with pytest.raises(ValueError, match="nope"):
            run_with_retries(fail, max_retries=0, label="test")
