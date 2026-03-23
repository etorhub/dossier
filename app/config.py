"""Load configuration from YAML files."""

from pathlib import Path
from typing import Any

import yaml

DEFAULTS: dict[str, Any] = {
    "llm": {
        "provider": "ollama",
        "model": "qwen2.5:7b",
        "host": "http://ollama:11434",
        "api_base": "",
        "timeout_seconds": 120,
        "max_retries": 3,
    },
    "embeddings": {
        "provider": "ollama",
        "model": "nomic-embed-text",
        "host": "http://ollama:11434",
        "api_base": "",
        "timeout_seconds": 60,
        "max_retries": 3,
        "max_input_chars": 8000,
    },
    "extraction": {
        "enabled": True,
        "min_content_length": 200,
        "batch_size": 30,
        "rate_limit_per_domain": 2.0,
        "timeout": 30,
    },
    "schedule": {
        "fetch_interval_minutes": 5,
        "enrichment_cron": "*/5 * * * *",
        "cluster_cron": "*/5 * * * *",
        "rewrite_cron": "*/5 * * * *",
        "rewrite_batch_size": 10,
        "rewrite_parallel_workers": 1,
        "fetcher": {
            "circuit_breaker_threshold": 5,
            "request_timeout_seconds": 30,
            "user_agent": "Dossier/0.1 (+https://github.com/etorhub/dossier)",
        },
    },
    "processing": {
        "articles_per_day": 10,
        "summary_sentences": 3,
        "rewrite_max_tokens": 2000,
        "cluster_window_hours": 24,
        "story_similarity_threshold": 0.90,
        "story_min_sources": 2,
        "story_value_delta": 0.05,
        "embed_batch_size": 50,
    },
    "server": {
        "port": 5000,
        "debug": False,
    },
    "rewriting": {
        "styles": [
            {"id": "neutral", "label": "Neutral", "prompt": "rewrite_cluster_neutral"},
            {"id": "simple", "label": "Simple", "prompt": "rewrite_cluster_simple"},
        ],
        "languages": [
            {"id": "ca", "label": "Catalan"},
            {"id": "es", "label": "Spanish"},
            {"id": "en", "label": "English"},
        ],
        "default_style": "neutral",
        "default_language": "ca",
    },
}


def load_config(config_path: str | Path | None = None) -> dict[str, Any]:
    """Load app config from YAML file, falling back to defaults if missing."""
    if config_path is None:
        config_path = Path(__file__).resolve().parent.parent / "config" / "app.yaml"
    path = Path(config_path)
    if not path.exists():
        return DEFAULTS.copy()
    with path.open() as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        return DEFAULTS.copy()
    return _deep_merge(DEFAULTS.copy(), data)


def get_topic_info(topic_id: str, config: dict[str, Any] | None = None) -> dict[str, str]:
    """Return {label, icon, emoji} for a topic. Falls back to topic_id if not in config."""
    if config is None:
        config = load_config()
    topics_cfg = config.get("topics", {}) or {}
    info = topics_cfg.get(topic_id, {})
    if isinstance(info, dict):
        label = info.get("label", topic_id.replace("_", " ").title())
        return {
            "label": label,
            "icon": info.get("icon", "newspaper"),
            "emoji": info.get("emoji", "📄"),
        }
    return {"label": str(topic_id), "icon": "newspaper", "emoji": "📄"}


def load_sources(sources_path: str | Path | None = None) -> list[dict[str, Any]]:
    """Load news sources from YAML file."""
    if sources_path is None:
        base = Path(__file__).resolve().parent.parent
        sources_path = base / "config" / "sources.yaml"
    path = Path(sources_path)
    if not path.exists():
        return []
    with path.open() as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict) or "sources" not in data:
        return []
    sources = data["sources"]
    return sources if isinstance(sources, list) else []


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Merge override into base recursively."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result
