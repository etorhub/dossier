"""Tests for app/config.py env-var overrides."""

from __future__ import annotations

import pytest

from app.config import _parse_bool, load_config


def test_llm_jobs_enabled_defaults_true() -> None:
    """Without the env var, LLM jobs are enabled (full worker)."""
    cfg = load_config()
    assert cfg["schedule"]["llm_jobs_enabled"] is True


@pytest.mark.parametrize("value", ["false", "0", "no", "off", "FALSE", " False "])
def test_llm_jobs_enabled_disabled_by_env(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    """Falsy strings disable the LLM jobs (light worker)."""
    monkeypatch.setenv("DOSSIER_LLM_JOBS_ENABLED", value)
    cfg = load_config()
    assert cfg["schedule"]["llm_jobs_enabled"] is False


@pytest.mark.parametrize("value", ["true", "1", "yes", "on", "anything"])
def test_llm_jobs_enabled_truthy_env(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    """Non-falsy strings keep the LLM jobs enabled."""
    monkeypatch.setenv("DOSSIER_LLM_JOBS_ENABLED", value)
    cfg = load_config()
    assert cfg["schedule"]["llm_jobs_enabled"] is True


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("false", False),
        ("0", False),
        ("no", False),
        ("off", False),
        ("", False),
        ("true", True),
        ("1", True),
        ("yes", True),
    ],
)
def test_parse_bool(value: str, expected: bool) -> None:
    assert _parse_bool(value) is expected
