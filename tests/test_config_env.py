"""Tests for environment variable overrides in load_config()."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from app.config import DEFAULTS, load_config


def test_schedule_defaults_use_safe_daily_cadence() -> None:
    """DEFAULTS is the safety net when config/app.yaml can't be read — it must
    fall back to the real daily cadence, never a fast dev-testing cron that
    would hammer paid inference endpoints."""
    schedule = DEFAULTS["schedule"]
    assert schedule["fetch_interval_minutes"] == 60
    assert schedule["enrichment_cron"] == "5 * * * *"
    assert schedule["cluster_cron"] == "15 * * * *"
    assert schedule["rewrite_cron"] == "0 6 * * *"


def test_load_config_warns_when_config_file_missing(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A WARNING is logged when config/app.yaml can't be found, so a
    misconfigured deployment is visible instead of silently falling back."""
    missing_path = tmp_path / "does-not-exist.yaml"
    with caplog.at_level(logging.WARNING, logger="app.config"):
        config = load_config(missing_path)
    assert config["schedule"]["rewrite_cron"] == "0 6 * * *"
    assert any("config/app.yaml not found" in r.message for r in caplog.records)


def test_llm_provider_env_overrides_yaml() -> None:
    with patch.dict(
        os.environ,
        {
            "LLM_PROVIDER": "vllm",
            "LLM_API_BASE": "https://example.modal.run/v1",
        },
        clear=False,
    ):
        config = load_config()
    assert config["llm"]["provider"] == "vllm"
    assert config["llm"]["api_base"] == "https://example.modal.run/v1"


def test_embed_provider_env_overrides_yaml() -> None:
    with patch.dict(
        os.environ,
        {
            "EMBED_PROVIDER": "vllm",
            "EMBED_API_BASE": "https://embed.example.modal.run/v1",
            "EMBED_API_KEY": "secret-token",
        },
        clear=False,
    ):
        config = load_config()
    assert config["embeddings"]["provider"] == "vllm"
    assert config["embeddings"]["api_base"] == "https://embed.example.modal.run/v1"
    assert config["embeddings"]["api_key"] == "secret-token"
