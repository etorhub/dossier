"""Load configuration from YAML files."""

import logging
import os
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

DEFAULTS: dict[str, Any] = {
    "paths": {
        "job_run_logs": "data/job_runs",
    },
    "llm": {
        "provider": "ollama",
        "model": "qwen2.5:14b",
        "rewrite_model": "qwen2.5:14b",
        "simplify_model": "qwen2.5:14b",
        "translate_model": "qwen2.5:14b",
        "host": "http://ollama:11434",
        "api_base": "",
        "timeout_seconds": 120,
        "max_retries": 3,
        # Low temperatures reduce typos and calques in rewrite / translate / proofread.
        "rewrite_temperature": 0.2,
        "simplify_temperature": 0.2,
        "translate_temperature": 0.15,
        "proofread_temperature": 0.1,
    },
    "embeddings": {
        "provider": "ollama",
        "model": "bge-m3",
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
        "abandon_after_hours": 4,  # articles pending longer than this are abandoned
        "cluster_gate_max_pending": 5,  # tolerate up to N pending before blocking cluster
    },
    "schedule": {
        # Safety-net defaults, used only if config/app.yaml can't be read at
        # runtime — must fail toward the safe daily cadence, never toward a
        # fast dev-testing cadence that would hammer paid inference endpoints.
        "fetch_interval_minutes": 60,
        "enrichment_cron": "5 * * * *",
        "cluster_cron": "15 * * * *",
        "rewrite_cron": "0 6 * * *",
        "highlight_cron": "15-59/30 * * * *",
        "rewrite_batch_size": 0,
        "rewrite_parallel_workers": 1,
        "fetcher": {
            "circuit_breaker_threshold": 5,
            "request_timeout_seconds": 30,
            "user_agent": "Dossier/0.1 (+https://github.com/etorhub/dossier)",
        },
    },
    "processing": {
        "articles_per_day": 10,
        "summary_sentences": 2,
        "rewrite_max_tokens": 4096,
        "rewrite_max_sources_per_story": 18,
        "rewrite_max_chars_per_article": 8000,
        "rewrite_max_articles_text_chars": 52000,
        # Second LLM pass: spelling, grammar, agreement only (after each draft rewrite).
        "rewrite_proofread_enabled": True,
        "cluster_window_hours": 24,
        "story_similarity_threshold": 0.92,
        "story_assignment_threshold": 0.95,
        "story_min_sources": 2,
        "story_value_delta": 0.05,
        "embed_batch_size": 0,
        "rewrite_cooldown_minutes": 60,
        "cluster_ann_candidates": 20,
        "cluster_use_ivfflat": False,
        "highlight_method": "ner",
    },
    "server": {
        "port": 5000,
        "debug": False,
    },
    "feed": {
        "promoted_content": {
            "enabled": True,
            "body_prefix_chars": 400,
            "patterns": [
                "contenido patrocinado",
                "contingut patrocinat",
                "con la colaboración de",
                "con la colaboracion de",
                "en colaboración con",
                "en colaboracion con",
                "sponsored content",
                "paid partnership",
            ],
        },
    },
    "rewriting": {
        "base_language": "es",
        "styles": [
            {"id": "neutral", "label": "Neutral", "prompt": "rewrite_cluster_neutral"},
        ],
        "languages": [
            {
                "id": "es",
                "label": "Spanish",
                "writing_note": (
                    "European Spanish. Correct gender/number agreement; "
                    "natural Spanish syntax (not English calques). Prefer "
                    "standard financial vocabulary (e.g. valoración). "
                    "Use suscriptores for paying followers, not subscriptores."
                ),
            },
        ],
        "default_style": "neutral",
        "default_language": "es",
    },
}


def load_config(config_path: str | Path | None = None) -> dict[str, Any]:
    """Load app config from YAML file, falling back to defaults if missing.

    Env overrides (take precedence over config/app.yaml when set):
      LLM_PROVIDER / LLM_API_BASE — rewrite provider (ollama local, vllm Modal prod)
      EMBED_PROVIDER / EMBED_API_BASE / EMBED_API_KEY — embedding provider
      DOSSIER_LLM_MODEL — overrides llm.model and all *_model task overrides
      DOSSIER_EMBEDDING_MODEL — overrides embeddings.model
    """
    if config_path is None:
        config_path = Path(__file__).resolve().parent.parent / "config" / "app.yaml"
    path = Path(config_path)
    if not path.exists():
        logger.warning(
            "config/app.yaml not found at %s — falling back to built-in defaults", path
        )
        config = DEFAULTS.copy()
    else:
        with path.open() as f:
            data = yaml.safe_load(f)
        config = _deep_merge(DEFAULTS.copy(), data) if isinstance(data, dict) else DEFAULTS.copy()

    _apply_env_str(config, "llm", "provider", "LLM_PROVIDER")
    _apply_env_str(config, "llm", "api_base", "LLM_API_BASE")
    _apply_env_str(config, "embeddings", "provider", "EMBED_PROVIDER")
    _apply_env_str(config, "embeddings", "api_base", "EMBED_API_BASE")
    _apply_env_str(config, "embeddings", "api_key", "EMBED_API_KEY")

    llm_model = os.environ.get("DOSSIER_LLM_MODEL")
    if llm_model:
        config["llm"]["model"] = llm_model
        config["llm"]["rewrite_model"] = llm_model
        config["llm"]["simplify_model"] = llm_model
        config["llm"]["translate_model"] = llm_model

    embedding_model = os.environ.get("DOSSIER_EMBEDDING_MODEL")
    if embedding_model:
        config["embeddings"]["model"] = embedding_model

    return config


def _apply_env_str(config: dict[str, Any], section: str, key: str, env_name: str) -> None:
    """Set config[section][key] from env when the variable is non-empty."""
    value = os.environ.get(env_name)
    if value is not None and value.strip():
        config.setdefault(section, {})[key] = value.strip()


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
