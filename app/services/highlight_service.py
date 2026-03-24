"""LLM highlighting pass: wraps significant terms in ** in story full_text."""

import logging
from dataclasses import dataclass
from typing import Any

from app.db import stories as db_stories
from app.llm.prompts import load_prompt
from app.llm.provider import LLMProvider, get_provider

logger = logging.getLogger(__name__)


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

    provider = get_provider(config, task="highlight")

    for row in rows:
        attempted += 1
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

    logger.info(
        "run_highlight_batch: attempted=%d succeeded=%d failed=%d",
        attempted, succeeded, failed,
    )
    return HighlightReport(attempted=attempted, succeeded=succeeded, failed=failed)
