#!/usr/bin/env python3
"""Benchmark rewrite cascade wall-clock time (sequential vs parallel workers).

Requires DATABASE_URL (or POSTGRES_* env vars) and at least one story with articles.

Examples::

    # Simulated LLM latency (no Ollama); compares worker=1 vs worker=4
    python scripts/benchmark_rewrite_llm.py --mock --limit 4 --mock-delay 0.05

    # Real Ollama / vLLM (uses config/app.yaml providers and models)
    python scripts/benchmark_rewrite_llm.py --limit 3

Environment: load ``.env`` from the repo root if present (python-dotenv).
"""

from __future__ import annotations

import argparse
import copy
import sys
import time
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

try:
    from dotenv import load_dotenv

    load_dotenv(_REPO_ROOT / ".env")
except ImportError:
    pass

_FAKE_LLM_OUTPUT = """TITLE:
Benchmark headline.

SUMMARY:
One. Two. Three.

FULL:
This is synthetic full text for benchmarking the rewrite pipeline duration.
"""


class _FakeLLMProvider:
    """Minimal stand-in for LLMProvider (sleep per call)."""

    def __init__(self, delay_seconds: float) -> None:
        self._delay = delay_seconds

    def complete(
        self,
        prompt: str,
        max_tokens: int = 1000,
        *,
        temperature: float | None = None,
    ) -> str:
        del prompt, max_tokens, temperature
        time.sleep(self._delay)
        return _FAKE_LLM_OUTPUT


def _build_work(limit: int) -> list[tuple[str, list[dict[str, Any]], bool]]:
    from app.db import stories as db_stories

    rows = db_stories.get_stories_with_articles_in_window(since=None)
    work: list[tuple[str, list[dict[str, Any]], bool]] = []
    for row in rows[:limit]:
        sid = row["story_id"]
        articles = db_stories.get_articles_in_story(sid)
        if articles:
            work.append((sid, articles, True))
    return work


def _run_once(
    label: str,
    work: list[tuple[str, list[dict[str, Any]], bool]],
    config: dict[str, Any],
    *,
    parallel_workers: int,
    rewrite_provider: Any,
    simplify_provider: Any,
    translate_provider: Any,
) -> float:
    from app.services.rewrite_service import _execute_cascading_rewrites

    base_language = config.get("rewriting", {}).get("base_language", "en")
    other_languages = [
        lang["id"]
        for lang in config.get("rewriting", {}).get("languages", [])
        if lang["id"] != base_language
    ]
    t0 = time.perf_counter()
    _execute_cascading_rewrites(
        work=work,
        config=config,
        base_language=base_language,
        other_languages=other_languages,
        rewrite_provider=rewrite_provider,
        simplify_provider=simplify_provider,
        translate_provider=translate_provider,
        parallel_workers=parallel_workers,
        translation_max_workers=parallel_workers,
    )
    elapsed = time.perf_counter() - t0
    print(f"  {label}: {elapsed:.2f}s (parallel_workers={parallel_workers})")
    return elapsed


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark rewrite cascade throughput.")
    parser.add_argument(
        "--limit",
        type=int,
        default=5,
        help="Max stories to benchmark (default: 5)",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Use fake LLM with fixed delay per call (no Ollama/vLLM)",
    )
    parser.add_argument(
        "--mock-delay",
        type=float,
        default=0.05,
        help="Seconds to sleep per LLM call when --mock (default: 0.05)",
    )
    parser.add_argument(
        "--workers-sequential",
        type=int,
        default=1,
        help="parallel_workers for first run (default: 1)",
    )
    parser.add_argument(
        "--workers-parallel",
        type=int,
        default=4,
        help="parallel_workers for second run (default: 4)",
    )
    args = parser.parse_args()

    from app.config import load_config

    config = load_config()
    work = _build_work(args.limit)
    if not work:
        print("No stories with articles found; nothing to benchmark.", file=sys.stderr)
        return 1

    print(f"Benchmarking {len(work)} stor(ies)…")

    if args.mock:
        delay = max(0.0, args.mock_delay)
        rp = sp = tp = _FakeLLMProvider(delay)
    else:
        from app.llm.provider import get_provider

        rp = get_provider(config, task="rewrite")
        sp = get_provider(config, task="simplify")
        tp = get_provider(config, task="translate")

    cfg_seq = copy.deepcopy(config)
    cfg_seq.setdefault("schedule", {})["rewrite_parallel_workers"] = args.workers_sequential
    cfg_par = copy.deepcopy(config)
    cfg_par.setdefault("schedule", {})["rewrite_parallel_workers"] = args.workers_parallel

    print("Run 1 (sequential-style workers):")
    t_seq = _run_once(
        "sequential",
        work,
        cfg_seq,
        parallel_workers=max(1, args.workers_sequential),
        rewrite_provider=rp,
        simplify_provider=sp,
        translate_provider=tp,
    )
    print("Run 2 (parallel workers):")
    t_par = _run_once(
        "parallel",
        work,
        cfg_par,
        parallel_workers=max(1, args.workers_parallel),
        rewrite_provider=rp,
        simplify_provider=sp,
        translate_provider=tp,
    )
    if t_par > 0:
        print(f"  Speedup vs run 1: {t_seq / t_par:.2f}x")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
