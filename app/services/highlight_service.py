"""LLM highlighting pass: wraps significant terms in ** in story full_text."""

import logging
import shutil
import sys
from dataclasses import dataclass
from typing import Any

from app.db import stories as db_stories
from app.llm.prompts import load_prompt
from app.llm.provider import LLMProvider, get_provider

logger = logging.getLogger(__name__)


def _render_highlight_progress(
    done: int,
    total: int,
    label: str,
    *,
    frame: int,
) -> None:
    """One-line stderr progress (TTY only). Matches enrich job UX."""
    if total <= 0 or not sys.stderr.isatty():
        return
    spin = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
    ch = spin[frame % len(spin)]
    pct = min(100, round(100.0 * done / total)) if total else 0
    bar_w = min(28, max(12, shutil.get_terminal_size((88, 24)).columns - 48))
    filled = min(bar_w, max(0, round(bar_w * done / total)))
    bar_f = "█" * filled + "░" * (bar_w - filled)
    safe = (label or "").replace("\n", " ").strip() or "—"
    if len(safe) > 40:
        safe = safe[:39] + "…"
    sys.stderr.write(
        f"\r\x1b[36m{ch}\x1b[0m highlight \x1b[32m{bar_f}\x1b[0m "
        f"\x1b[1m{done}\x1b[0m/\x1b[1m{total}\x1b[0m {pct}%  "
        f"\x1b[2m{safe}\x1b[0m\x1b[K"
    )
    sys.stderr.flush()


@dataclass
class HighlightReport:
    """Summary of a highlight batch run."""

    attempted: int
    succeeded: int
    failed: int


def highlight_story(
    story_id: str,
    full_text: str,
    style: str,
    language: str,
    config: dict[str, Any],
    *,
    provider: LLMProvider | None = None,
) -> bool:
    """Call LLM to highlight significant terms in full_text, store result. Returns True on success."""
    if provider is None:
        provider = get_provider(config, task="highlight")

    processing = config.get("processing", {})
    max_tokens = int(processing.get("rewrite_max_tokens") or 4096)

    prompt_template = load_prompt("highlight_terms")
    prompt = prompt_template.format(full_text=full_text)

    try:
        response = provider.complete(prompt, max_tokens=max_tokens, temperature=0.0)
        highlighted = response.strip()
        if not highlighted:
            logger.warning(
                "highlight_story: empty response for story_id=%s style=%s language=%s",
                story_id, style, language,
            )
            return False
        db_stories.update_story_rewrite_highlight(story_id, style, language, highlighted)
        logger.debug(
            "highlight_story: done story_id=%s style=%s language=%s", story_id, style, language
        )
        return True
    except Exception as e:
        logger.warning(
            "highlight_story failed story_id=%s style=%s language=%s: %s",
            story_id, style, language, e,
        )
        return False


def run_highlight_batch(config: dict[str, Any] | None = None) -> HighlightReport:
    """Process all story_rewrites rows missing highlighted_full_text."""
    from app.config import load_config

    if config is None:
        config = load_config()

    rows = db_stories.get_stories_needing_highlight()
    attempted = 0
    succeeded = 0
    failed = 0

    if not rows:
        logger.info("run_highlight_batch: nothing to highlight")
        return HighlightReport(attempted=0, succeeded=0, failed=0)

    total = len(rows)
    logger.info("Highlight starting: %d story rewrites pending", total)

    provider = get_provider(config, task="highlight")

    try:
        for row in rows:
            attempted += 1
            label = f"{row['story_id'][:8]} {row['style']}/{row['language']}"
            _render_highlight_progress(attempted - 1, total, label, frame=attempted - 1)
            ok = highlight_story(
                story_id=row["story_id"],
                full_text=row["full_text"],
                style=row["style"],
                language=row["language"],
                config=config,
                provider=provider,
            )
            if ok:
                succeeded += 1
            else:
                failed += 1
            _render_highlight_progress(attempted, total, label, frame=attempted)
    finally:
        if sys.stderr.isatty() and total > 0:
            sys.stderr.write("\n")
            sys.stderr.flush()

    logger.info(
        "Highlight complete: %d succeeded, %d failed",
        succeeded, failed,
    )
    return HighlightReport(attempted=attempted, succeeded=succeeded, failed=failed)
