"""Tests for environment variable overrides in load_config()."""

from __future__ import annotations

import os
from unittest.mock import patch

from app.config import load_config


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
