"""LLM rewrite orchestration. Runs on schedule for all (style, language) variants."""

import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from app.config import load_config

logger = logging.getLogger(__name__)
from app.db import stories as db_stories
from app.llm.prompts import load_prompt
from app.llm.provider import LLMProvider, get_provider


@dataclass
class RewriteReport:
    """Summary of a rewrite batch run."""

    variants_processed: int
    stories_attempted: int
    stories_succeeded: int
    stories_failed: int


def _strip_markdown_bold(text: str) -> str:
    """Remove markdown bold markers (**) from the start and end of text."""
    s = text.strip()
    if s.startswith("**"):
        s = s[2:].lstrip()
    if s.endswith("**"):
        s = s[:-2].rstrip()
    return s.strip()


def _parse_story_llm_response(text: str) -> tuple[str, str, str]:
    """Parse LLM output into (title, summary, full_text). Raises ValueError on bad format."""
    if not re.search(r"TITLE\s*:", text, re.I):
        raise ValueError("Response missing TITLE:, SUMMARY:, or FULL: sections")
    if not re.search(r"SUMMARY\s*:", text, re.I):
        raise ValueError("Response missing TITLE:, SUMMARY:, or FULL: sections")
    if not re.search(r"FULL\s*:", text, re.I):
        raise ValueError("Response missing TITLE:, SUMMARY:, or FULL: sections")

    parts = re.split(r"FULL\s*:", text, maxsplit=1, flags=re.I)
    if len(parts) != 2:
        raise ValueError("Response missing FULL: section")
    header_part = parts[0]
    full_text = parts[1].strip()

    title = ""
    title_match = re.search(r"TITLE\s*:(.*?)(?=SUMMARY\s*:|$)", header_part, re.I | re.DOTALL)
    if title_match:
        title = title_match.group(1).strip()

    summary = ""
    summary_match = re.search(r"SUMMARY\s*:(.*?)(?=FULL\s*:|$)", header_part, re.I | re.DOTALL)
    if summary_match:
        summary = summary_match.group(1).strip()

    if not title or not summary or not full_text:
        raise ValueError("Empty TITLE, SUMMARY, or FULL section")
    return (
        _strip_markdown_bold(title),
        _strip_markdown_bold(summary),
        _strip_markdown_bold(full_text),
    )


# Backwards compatibility alias
_parse_cluster_llm_response = _parse_story_llm_response


def _build_articles_text(articles: list[dict[str, Any]]) -> str:
    """Build concatenated text of all articles for the prompt."""
    blocks = []
    for i, art in enumerate(articles, 1):
        title = (art.get("title") or "").strip()
        full = (art.get("full_text") or "").strip()
        raw = (art.get("raw_text") or "").strip()
        text = full or raw
        if not text:
            continue
        blocks.append(f"[Source {i}: {title}]\n\n{text}")
    return "\n\n---\n\n".join(blocks) if blocks else ""


def _build_article_text_from_rewrite(rewrite: dict[str, Any]) -> str:
    """Build article text from a rewrite (title, summary, full_text) for simplify/translate prompts."""
    title = (rewrite.get("title") or "").strip()
    summary = (rewrite.get("summary") or "").strip()
    full_text = (rewrite.get("full_text") or "").strip()
    return f"TITLE:\n{title}\n\nSUMMARY:\n{summary}\n\nFULL:\n{full_text}"


def _get_language_label(config: dict[str, Any], lang_id: str) -> str:
    """Return the display label for a language id (e.g. 'en' -> 'English')."""
    for lang in config.get("rewriting", {}).get("languages", []):
        if lang.get("id") == lang_id:
            return lang.get("label", lang_id)
    return lang_id


def _get_style_description(config: dict[str, Any], style_id: str) -> str:
    """Return a brief style description for the translate prompt."""
    descriptions = {
        "neutral": "Journalistic. Formal and well-written. Preserve original complexity and nuance.",
        "simple": "Short sentences. Simple vocabulary. No jargon. Remain factual and complete.",
    }
    return descriptions.get(style_id, "Preserve the tone of the source.")


def _get_rewriting_variants(config: dict[str, Any]) -> list[tuple[str, str]]:
    """Return list of (style_id, language_id) from config."""
    rewriting = config.get("rewriting", {})
    styles = rewriting.get("styles", [])
    languages = rewriting.get("languages", [])
    if not styles or not languages:
        return [("neutral", "ca")]
    return [
        (s["id"], lang["id"])
        for s in styles
        for lang in languages
    ]


def rewrite_story(
    story_id: str,
    articles: list[dict[str, Any]],
    style: str,
    language: str,
    config: dict[str, Any],
    *,
    provider: LLMProvider | None = None,
    clear_needs_rewrite: bool = True,
) -> bool:
    """Rewrite a story for (style, language) and store. Returns True on success."""
    logger.debug(
        "rewrite_story: story_id=%s style=%s language=%s articles=%d",
        story_id,
        style,
        language,
        len(articles),
    )
    articles_text = _build_articles_text(articles)
    if not articles_text:
        db_stories.insert_story_rewrite(
            story_id=story_id,
            style=style,
            language=language,
            title=None,
            summary=None,
            full_text=None,
            rewrite_failed=True,
            error_message="Articles have no full_text or raw_text",
        )
        return False

    rewriting = config.get("rewriting", {})
    styles_cfg = {s["id"]: s for s in rewriting.get("styles", [])}
    prompt_name = styles_cfg.get(style, {}).get("prompt", "rewrite_cluster_neutral")
    processing = config.get("processing", {})
    summary_sentences = processing.get("summary_sentences", 3)
    max_tokens = processing.get("rewrite_max_tokens", 2000)
    prompt_language = _get_language_label(config, language)

    prompt_template = load_prompt(prompt_name)
    prompt = prompt_template.format(
        articles_text=articles_text,
        language=prompt_language,
        summary_sentences=summary_sentences,
    )

    if provider is None:
        provider = get_provider(config, task="rewrite")
    try:
        logger.debug(
            "rewrite_story: calling LLM story_id=%s style=%s language=%s",
            story_id,
            style,
            language,
        )
        response = provider.complete(prompt, max_tokens=max_tokens)
        title, summary, full_text = _parse_story_llm_response(response)
        db_stories.insert_story_rewrite(
            story_id=story_id,
            style=style,
            language=language,
            title=title,
            summary=summary,
            full_text=full_text,
            rewrite_failed=False,
        )
        if clear_needs_rewrite:
            db_stories.set_story_needs_rewrite(story_id, False)
        logger.debug("rewrite_story: done story_id=%s ok=True", story_id)
        return True
    except Exception as e:
        err_msg = str(e)[:500]
        db_stories.insert_story_rewrite(
            story_id=story_id,
            style=style,
            language=language,
            title=None,
            summary=None,
            full_text=None,
            rewrite_failed=True,
            error_message=err_msg,
        )
        logger.debug(
            "rewrite_story: done story_id=%s ok=False error=%s",
            story_id,
            err_msg,
        )
        return False


def _simplify_rewrite(
    story_id: str,
    neutral_rewrite: dict[str, Any],
    config: dict[str, Any],
    provider: LLMProvider,
) -> bool:
    """Simplify a neutral English rewrite to simple English. Returns True on success."""
    article_text = _build_article_text_from_rewrite(neutral_rewrite)
    processing = config.get("processing", {})
    summary_sentences = processing.get("summary_sentences", 3)
    max_tokens = processing.get("rewrite_max_tokens", 2000)

    prompt_template = load_prompt("simplify_article")
    prompt = prompt_template.format(
        article_text=article_text,
        summary_sentences=summary_sentences,
    )

    try:
        response = provider.complete(prompt, max_tokens=max_tokens)
        title, summary, full_text = _parse_story_llm_response(response)
        db_stories.insert_story_rewrite(
            story_id=story_id,
            style="simple",
            language="en",
            title=title,
            summary=summary,
            full_text=full_text,
            rewrite_failed=False,
        )
        return True
    except Exception as e:
        err_msg = str(e)[:500]
        db_stories.insert_story_rewrite(
            story_id=story_id,
            style="simple",
            language="en",
            title=None,
            summary=None,
            full_text=None,
            rewrite_failed=True,
            error_message=err_msg,
        )
        logger.debug("_simplify_rewrite: story_id=%s failed: %s", story_id, err_msg)
        return False


def _translate_rewrite(
    story_id: str,
    source_rewrite: dict[str, Any],
    style: str,
    target_lang_id: str,
    config: dict[str, Any],
    provider: LLMProvider,
) -> bool:
    """Translate a rewrite to the target language. Returns True on success."""
    article_text = _build_article_text_from_rewrite(source_rewrite)
    target_language = _get_language_label(config, target_lang_id)
    style_description = _get_style_description(config, style)
    processing = config.get("processing", {})
    summary_sentences = processing.get("summary_sentences", 3)
    max_tokens = processing.get("rewrite_max_tokens", 2000)

    prompt_template = load_prompt("translate_article")
    prompt = prompt_template.format(
        article_text=article_text,
        target_language=target_language,
        style_description=style_description,
        summary_sentences=summary_sentences,
    )

    try:
        response = provider.complete(prompt, max_tokens=max_tokens)
        title, summary, full_text = _parse_story_llm_response(response)
        db_stories.insert_story_rewrite(
            story_id=story_id,
            style=style,
            language=target_lang_id,
            title=title,
            summary=summary,
            full_text=full_text,
            rewrite_failed=False,
        )
        return True
    except Exception as e:
        err_msg = str(e)[:500]
        db_stories.insert_story_rewrite(
            story_id=story_id,
            style=style,
            language=target_lang_id,
            title=None,
            summary=None,
            full_text=None,
            rewrite_failed=True,
            error_message=err_msg,
        )
        logger.debug(
            "_translate_rewrite: story_id=%s style=%s lang=%s failed: %s",
            story_id,
            style,
            target_lang_id,
            err_msg,
        )
        return False


def _rewrite_story_cascading(
    story_id: str,
    articles: list[dict[str, Any]],
    config: dict[str, Any],
    needs_full_regen: bool,
    existing_rewrites: dict[tuple[str, str], dict[str, Any]],
    base_language: str,
    other_languages: list[str],
    rewrite_provider: LLMProvider,
    simplify_provider: LLMProvider,
    translate_provider: LLMProvider,
) -> tuple[int, int]:
    """Cascade: neutral/en -> simple/en -> translate both. Returns (succeeded, failed)."""
    succeeded = 0
    failed = 0

    # Step 1: Neutral English (merge sources)
    neutral_key = ("neutral", base_language)
    if needs_full_regen or neutral_key not in existing_rewrites:
        ok = rewrite_story(
            story_id=story_id,
            articles=articles,
            style="neutral",
            language=base_language,
            config=config,
            provider=rewrite_provider,
            clear_needs_rewrite=False,
        )
        if not ok:
            return (succeeded, failed + 1)
        succeeded += 1
        existing_rewrites[neutral_key] = {
            "title": None,
            "summary": None,
            "full_text": None,
        }
        # Reload from DB to get the actual values
        all_rewrites = db_stories.get_all_rewrites_for_story(story_id)
        existing_rewrites[neutral_key] = all_rewrites.get(neutral_key, {})

    neutral_rewrite = existing_rewrites.get(neutral_key)
    if not neutral_rewrite or not neutral_rewrite.get("title"):
        return (succeeded, failed + 1)

    # Step 2: Simple English (simplify)
    simple_key = ("simple", base_language)
    if needs_full_regen or simple_key not in existing_rewrites:
        ok = _simplify_rewrite(
            story_id=story_id,
            neutral_rewrite=neutral_rewrite,
            config=config,
            provider=simplify_provider,
        )
        if not ok:
            failed += 1
        else:
            succeeded += 1
            all_rewrites = db_stories.get_all_rewrites_for_story(story_id)
            existing_rewrites[simple_key] = all_rewrites.get(simple_key, {})

    # Step 3: Translate to other languages
    simple_rewrite = existing_rewrites.get(simple_key)
    for lang_id in other_languages:
        for style in ("neutral", "simple"):
            key = (style, lang_id)
            if needs_full_regen or key not in existing_rewrites:
                source = neutral_rewrite if style == "neutral" else (simple_rewrite or {})
                if not source or not source.get("title"):
                    continue
                ok = _translate_rewrite(
                    story_id=story_id,
                    source_rewrite=source,
                    style=style,
                    target_lang_id=lang_id,
                    config=config,
                    provider=translate_provider,
                )
                if ok:
                    succeeded += 1
                else:
                    failed += 1

    db_stories.set_story_needs_rewrite(story_id, False)
    return (succeeded, failed)


def _gather_rewrite_work(
    variants: list[tuple[str, str]],
    since: datetime | None,
    batch_size: int,
) -> list[tuple[str, list[dict[str, Any]], bool]]:
    """Return list of (story_id, articles, needs_full_regen) needing rewrite."""
    limit = None if batch_size <= 0 else batch_size
    stories = db_stories.get_stories_needing_any_rewrite(
        variants=variants,
        since=since,
        limit=limit,
    )
    work: list[tuple[str, list[dict[str, Any]], bool]] = []
    for row in stories:
        story_id = row["story_id"]
        needs_rewrite = row.get("needs_rewrite", False)
        articles = db_stories.get_articles_in_story(story_id)
        if articles:
            work.append((story_id, articles, needs_rewrite))
    return work


def _execute_cascading_rewrites(
    work: list[tuple[str, list[dict[str, Any]], bool]],
    config: dict[str, Any],
    base_language: str,
    other_languages: list[str],
    rewrite_provider: LLMProvider,
    simplify_provider: LLMProvider,
    translate_provider: LLMProvider,
) -> tuple[int, int]:
    """Run cascading rewrites for work items. Returns (succeeded, failed)."""
    total = len(work)
    succeeded = 0
    failed = 0
    for i, (story_id, articles, needs_full_regen) in enumerate(work, 1):
        existing = db_stories.get_all_rewrites_for_story(story_id)
        s, f = _rewrite_story_cascading(
            story_id=story_id,
            articles=articles,
            config=config,
            needs_full_regen=needs_full_regen,
            existing_rewrites=existing,
            base_language=base_language,
            other_languages=other_languages,
            rewrite_provider=rewrite_provider,
            simplify_provider=simplify_provider,
            translate_provider=translate_provider,
        )
        succeeded += s
        failed += f
        short_id = story_id[:12]
        logger.info(
            "    [%d/%d] %s... %d ok, %d fail",
            i,
            total,
            short_id,
            s,
            f,
        )
    return (succeeded, failed)


def run_rewrite_batch(config: dict[str, Any]) -> RewriteReport:
    """Process stories via cascade: neutral EN from sources, simplify, translate both."""
    logger.info("━━ Rewrite job starting (cascade: rewrite → simplify → translate)")
    processing = config.get("processing", {})
    window_hours = processing.get("cluster_window_hours", 24)
    since = (
        datetime.now(UTC) - timedelta(hours=window_hours)
        if window_hours
        else None
    )
    schedule_cfg = config.get("schedule", {})
    batch_size = int(schedule_cfg.get("rewrite_batch_size") or 0)

    variants = _get_rewriting_variants(config)
    base_language = config.get("rewriting", {}).get("base_language", "en")
    other_languages = [
        lang["id"]
        for lang in config.get("rewriting", {}).get("languages", [])
        if lang["id"] != base_language
    ]

    variant_str = ", ".join(f"{s}/{l}" for s, l in variants)
    batch_desc = "unlimited" if batch_size <= 0 else str(batch_size)
    logger.info(
        "  Variants: %s (batch_size=%s, base=%s)",
        variant_str or "none",
        batch_desc,
        base_language,
    )

    work = _gather_rewrite_work(variants, since, batch_size)
    if not work:
        logger.info("  No stories needing rewrite")
        return RewriteReport(
            variants_processed=len(variants),
            stories_attempted=0,
            stories_succeeded=0,
            stories_failed=0,
        )

    logger.info("  Rewriting %d story(ies) (cascade)...", len(work))
    logger.info("  Loading LLM providers (rewrite, simplify, translate)...")
    rewrite_provider = get_provider(config, task="rewrite")
    simplify_provider = get_provider(config, task="simplify")
    translate_provider = get_provider(config, task="translate")

    stories_succeeded, stories_failed = _execute_cascading_rewrites(
        work=work,
        config=config,
        base_language=base_language,
        other_languages=other_languages,
        rewrite_provider=rewrite_provider,
        simplify_provider=simplify_provider,
        translate_provider=translate_provider,
    )

    stories_attempted = len(work)
    logger.info(
        "━━ Rewrite complete: %d stories, %d variants ok, %d failed",
        stories_attempted,
        stories_succeeded,
        stories_failed,
    )
    return RewriteReport(
        variants_processed=len(variants),
        stories_attempted=stories_attempted,
        stories_succeeded=stories_succeeded,
        stories_failed=stories_failed,
    )


# Backwards compatibility alias
rewrite_cluster = rewrite_story


