"""Tests for shared HTTP / retry helpers."""

from unittest.mock import patch

import pytest

from app.llm.http_utils import run_with_retries


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
            raise ConnectionError("temporary")
        return "ok"

    with patch("app.llm.http_utils.time.sleep"):
        assert run_with_retries(fn, max_retries=3, label="test") == "ok"
    assert attempts == 2


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
