"""LLM rewrite orchestration. Runs on schedule for all (style, language) variants."""

import logging
import os
import re
import shutil
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from app.db import stories as db_stories
from app.llm.http_utils import (
    is_ollama_connection_failure,
    quiet_http_library_info_logs,
)
from app.llm.prompts import load_prompt
from app.llm.provider import LLMProvider, get_provider

logger = logging.getLogger(__name__)


class RewriteBatchAbort(Exception):
    """LLM host unreachable; abort the rest of this batch (like cluster embed stop)."""


def _llm_host_for_logging(config: dict[str, Any]) -> str:
    llm = config.get("llm") or {}
    return str(llm.get("host") or os.environ.get("OLLAMA_HOST") or "http://ollama:11434")

_rewrite_progress_lock = threading.Lock()

# Prepended to merge-source rewrite prompts so small models keep TITLE:/SUMMARY:/FULL: in {language}.
_REWRITE_OUTPUT_CONTRACT_PREFIX = (
    "[Output contract — highest priority]\n"
    "Line 1 of your reply must be TITLE: (character T first). No preamble, markdown headings, "
    "or numbered summaries per source. Use TITLE:, SUMMARY:, FULL: then write only in {language}.\n"
    "TITLE, SUMMARY, and FULL must read as published news: report facts directly. "
    "Do not describe the text, an 'update', a 'summary', or 'multiple news items'—no meta framing.\n\n"
)


def _rewrite_story_title_snippet(articles: list[dict[str, Any]], story_id: str) -> str:
    if articles:
        t = str(articles[0].get("title") or "").strip()
        if t:
            return t
    return story_id[:12] if story_id else "—"


def _render_rewrite_progress(
    done: int,
    total: int,
    title: str,
    *,
    frame: int,
) -> None:
    """One-line stderr progress (TTY only). Same layout as cluster embed bar."""
    if total <= 0 or not sys.stderr.isatty():
        return
    with _rewrite_progress_lock:
        spin = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
        ch = spin[frame % len(spin)]
        pct = min(100, round(100.0 * done / total)) if total else 0
        bar_w = min(28, max(12, shutil.get_terminal_size((88, 24)).columns - 48))
        filled = min(bar_w, max(0, round(bar_w * done / total)))
        bar_f = "█" * filled + "░" * (bar_w - filled)
        safe = (title or "").replace("\n", " ").strip() or "—"
        if len(safe) > 40:
            safe = safe[:39] + "…"
        sys.stderr.write(
            f"\r\x1b[36m{ch}\x1b[0m rewrite \x1b[32m{bar_f}\x1b[0m "
            f"\x1b[1m{done}\x1b[0m/\x1b[1m{total}\x1b[0m {pct}%  "
            f"\x1b[2m{safe}\x1b[0m\x1b[K"
        )
        sys.stderr.flush()


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


def _strip_optional_markdown_fences(text: str) -> str:
    """If the model wraps the reply in a fenced block, strip it for header parsing."""
    raw = text.lstrip("\ufeff")
    s = raw.strip()
    if not s.startswith("```"):
        return raw
    without_open = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", s, count=1)
    without_close = re.sub(r"\s*```\s*$", "", without_open.strip())
    return without_close.lstrip("\n")


# LLM prompts ask for TITLE:/SUMMARY:/FULL: but "output exclusively in {language}"
# often makes models use localized headers (e.g. TÍTULO:/RESUMEN:/COMPLETO:).
# Longer patterns must run before shorter prefixes (e.g. TEXTO COMPLETO before COMPLETO).
_HEADER_NORMALIZATIONS: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(pat, re.I | re.M), repl)
    for pat, repl in (
        # Markdown ATX headers (despite "plain text only" in the prompt)
        (r"^#{1,6}\s*TEXTO\s+COMPLETO\s*:", "FULL:"),
        (r"^#{1,6}\s*TEXT\s+COMPLET\s*:", "FULL:"),
        (r"^#{1,6}\s*(?:ARTÍCULO|ARTICULO)\s+COMPLETO\s*:", "FULL:"),
        (r"^#{1,6}\s*RÉSUMÉ\s*:", "SUMMARY:"),
        (r"^#{1,6}\s*RESUMEN\s*:", "SUMMARY:"),
        (r"^#{1,6}\s*SUMMARY\s*:", "SUMMARY:"),
        (r"^#{1,6}\s*TÍTULO\s*:", "TITLE:"),
        (r"^#{1,6}\s*TITULO\s*:", "TITLE:"),
        (r"^#{1,6}\s*TITLE\s*:", "TITLE:"),
        (r"^#{1,6}\s*FULL\s*:", "FULL:"),
        (r"^#{1,6}\s*COMPLETO\s*:", "FULL:"),
        (r"^#{1,6}\s*COMPLET\s*:", "FULL:"),
        # Line that is only a bold section label
        (r"^\*{0,2}\s*TÍTULO\s*:\*{0,2}\s*$", "TITLE:"),
        (r"^\*{0,2}\s*TITULO\s*:\*{0,2}\s*$", "TITLE:"),
        (r"^\*{0,2}\s*TITLE\s*:\*{0,2}\s*$", "TITLE:"),
        (r"^\*{0,2}\s*RESUMEN\s*:\*{0,2}\s*$", "SUMMARY:"),
        (r"^\*{0,2}\s*SUMMARY\s*:\*{0,2}\s*$", "SUMMARY:"),
        (r"^\*{0,2}\s*FULL\s*:\*{0,2}\s*$", "FULL:"),
        (r"^\*{0,2}\s*COMPLETO\s*:\*{0,2}\s*$", "FULL:"),
        # Spanish synonyms
        (r"^ENCABEZADO\s*:", "TITLE:"),
        (r"^SINOPSIS\s*:", "SUMMARY:"),
        (r"^CUERPO\s*:", "FULL:"),
        (r"^DESARROLLO\s*:", "FULL:"),
        # FULL
        (r"^TEXTO\s+COMPLETO\s*:", "FULL:"),
        (r"^TEXT\s+COMPLET\s*:", "FULL:"),
        (r"^(?:ARTÍCULO|ARTICULO)\s+COMPLETO\s*:", "FULL:"),
        (r"^VOLLSTÄNDIGER\s+TEXT\s*:", "FULL:"),
        (r"^TEXTE\s+COMPLET\s*:", "FULL:"),
        (r"^VOLLTEXT\s*:", "FULL:"),
        (r"^COMPLETO\s*:", "FULL:"),
        (r"^COMPLET\s*:", "FULL:"),
        (r"^CORPS\s*:", "FULL:"),
        # SUMMARY
        (r"^RESUMEN\s*:", "SUMMARY:"),
        (r"^ZUSAMMENFASSUNG\s*:", "SUMMARY:"),
        (r"^RÉSUMÉ\s*:", "SUMMARY:"),
        (r"^RESUME\s*:", "SUMMARY:"),
        (r"^RESUM\s*:", "SUMMARY:"),
        # TITLE
        (r"^TÍTULO\s*:", "TITLE:"),
        (r"^TITULO\s*:", "TITLE:"),
        (r"^TÍTOL\s*:", "TITLE:"),
        (r"^TITOL\s*:", "TITLE:"),
        (r"^TITRE\s*:", "TITLE:"),
        (r"^TITEL\s*:", "TITLE:"),
    )
)


def _normalize_story_llm_section_headers(text: str) -> str:
    """Replace localized section headers with TITLE:/SUMMARY:/FULL: for parsing."""
    out = _strip_optional_markdown_fences(text)
    for pattern, repl in _HEADER_NORMALIZATIONS:
        out = pattern.sub(repl, out)
    return out


def _strip_preamble_before_first_title(text: str) -> str:
    """If the model adds chatter before TITLE:, parse from the first TITLE: line."""
    m = re.search(r"(?m)^TITLE\s*:", text, re.I)
    if not m:
        return text
    return text[m.start() :].lstrip()


def _derive_title_from_summary(summary: str) -> str:
    """Headline when the model emits TITLE: with no text (common with long merged prompts)."""
    s = _strip_markdown_bold((summary or "").strip())
    if not s:
        return ""
    first_sentence = s.split(".")[0].strip()
    candidate = first_sentence if first_sentence else s
    if len(candidate) > 220:
        return candidate[:217].rstrip() + "..."
    return candidate


def _parse_story_llm_response(text: str) -> tuple[str, str, str]:
    """Parse LLM output into (title, summary, full_text). Raises ValueError on bad format."""
    text = _normalize_story_llm_section_headers(text)
    text = _strip_preamble_before_first_title(text)
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

    if not title and summary:
        title = _derive_title_from_summary(summary)

    if not title or not summary or not full_text:
        raise ValueError("Empty TITLE, SUMMARY, or FULL section")
    return (
        _strip_markdown_bold(title),
        _strip_markdown_bold(summary),
        _strip_markdown_bold(full_text),
    )


# Backwards compatibility alias
_parse_cluster_llm_response = _parse_story_llm_response


_TRUNC_MARKER = "\n\n[... source text truncated ...]"
_MERGED_TRUNC_MARKER = "\n\n---\n\n[... merged sources truncated for model context ...]"


def _processing_int(processing: dict[str, Any], key: str, default: int) -> int:
    """Read int from processing; missing key uses default. Value 0 means unlimited for caps."""
    raw = processing.get(key)
    if raw is None:
        return default
    return int(raw)


def _build_articles_text_for_rewrite(
    articles: list[dict[str, Any]],
    processing: dict[str, Any],
) -> tuple[str, dict[str, Any]]:
    """Build articles_text with caps so prompts stay inside typical local LLM context.

    Defaults (when keys omitted) match config/app.yaml. Set any cap to 0 for unlimited.
    """
    max_sources = _processing_int(processing, "rewrite_max_sources_per_story", 18)
    max_per_article = _processing_int(processing, "rewrite_max_chars_per_article", 8000)
    max_total = _processing_int(processing, "rewrite_max_articles_text_chars", 52000)

    n_total = len(articles)
    work = articles[:max_sources] if max_sources > 0 else list(articles)
    capped_source_count = n_total > len(work)
    per_article_truncated = False

    blocks: list[str] = []
    for i, art in enumerate(work, 1):
        title = (art.get("title") or "").strip()
        full = (art.get("full_text") or "").strip()
        raw = (art.get("raw_text") or "").strip()
        text = full or raw
        if not text:
            continue
        if max_per_article > 0 and len(text) > max_per_article:
            keep = max_per_article - len(_TRUNC_MARKER)
            if keep > 200:
                text = text[:keep].rstrip() + _TRUNC_MARKER
                per_article_truncated = True
        blocks.append(f"[Source {i}: {title}]\n\n{text}")

    out = "\n\n---\n\n".join(blocks) if blocks else ""
    hard_truncated = False
    if max_total > 0 and len(out) > max_total:
        room = max_total - len(_MERGED_TRUNC_MARKER)
        if room > 200:
            out = out[:room].rstrip() + _MERGED_TRUNC_MARKER
        else:
            out = _MERGED_TRUNC_MARKER.strip()
        hard_truncated = True

    meta: dict[str, Any] = {
        "sources_total": n_total,
        "sources_used": len(work),
        "capped_source_count": capped_source_count,
        "articles_text_chars": len(out),
        "per_article_truncated": per_article_truncated,
        "hard_truncated": hard_truncated,
    }
    return out, meta


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
        "neutral": (
            "Wire-style journalism: formal, neutral, inverted pyramid; direct facts; "
            "no meta framing ('this article', 'this update', 'various news')."
        ),
        "simple": (
            "Short sentences, simple words, same journalistic standards: lead with the news, "
            "no meta framing."
        ),
    }
    return descriptions.get(style_id, "Preserve the tone of the source.")


def _llm_task_temperature(config: dict[str, Any], task: str) -> float:
    """Return sampling temperature for rewrite, simplify, translate, or proofread."""
    llm = config.get("llm") or {}
    key = f"{task}_temperature"
    raw = llm.get(key)
    if raw is None:
        fallbacks = {
            "rewrite": 0.2,
            "simplify": 0.2,
            "translate": 0.15,
            "proofread": 0.1,
        }
        return float(fallbacks.get(task, 0.2))
    return float(raw)


def _get_language_writing_note(config: dict[str, Any], lang_id: str) -> str:
    """Optional per-language guidance for translation (from rewriting.languages)."""
    for lang in config.get("rewriting", {}).get("languages", []):
        if lang.get("id") == lang_id:
            raw = lang.get("writing_note")
            if isinstance(raw, str) and raw.strip():
                return raw.strip()
            return ""
    return ""


def _writing_note_section_for_translate(config: dict[str, Any], lang_id: str) -> str:
    """Markdown section injected into translate_article.txt, or empty."""
    note = _get_language_writing_note(config, lang_id)
    if not note:
        return ""
    return f"## Locale and register for {lang_id}\n{note}\n"


def _proofread_if_enabled(
    provider: LLMProvider,
    title: str,
    summary: str,
    full_text: str,
    language_label: str,
    config: dict[str, Any],
) -> tuple[str, str, str]:
    """Optional second pass: spelling, grammar, agreement only. Keeps draft on failure."""
    proc = config.get("processing") or {}
    if proc.get("rewrite_proofread_enabled") is False:
        return title, summary, full_text
    max_tokens = int(proc.get("rewrite_max_tokens") or 4096)
    temp = _llm_task_temperature(config, "proofread")
    prompt_template = load_prompt("proofread_article")
    prompt = prompt_template.format(
        language=language_label,
        title=title,
        summary=summary,
        full_text=full_text,
    )
    try:
        response = provider.complete(prompt, max_tokens=max_tokens, temperature=temp)
        return _parse_story_llm_response(response)
    except Exception as e:
        if is_ollama_connection_failure(e):
            raise RewriteBatchAbort(str(e)) from e
        logger.debug("proofread failed, using draft: %s", e)
        return title, summary, full_text


def _configured_style_ids(config: dict[str, Any]) -> list[str]:
    """Ordered style ids from rewriting.styles; default neutral when empty."""
    styles = config.get("rewriting", {}).get("styles", [])
    out: list[str] = []
    for s in styles:
        if isinstance(s, dict):
            sid = s.get("id")
            if isinstance(sid, str) and sid.strip():
                out.append(sid.strip())
    return out if out else ["neutral"]


def _get_rewriting_variants(config: dict[str, Any]) -> list[tuple[str, str]]:
    """Return list of (style_id, language_id) from config."""
    rewriting = config.get("rewriting", {})
    style_ids = _configured_style_ids(config)
    languages = rewriting.get("languages", [])
    if not languages:
        return [("neutral", "ca")]
    return [(sid, lang["id"]) for sid in style_ids for lang in languages]


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
    processing = config.get("processing", {})
    articles_text, _input_meta = _build_articles_text_for_rewrite(articles, processing)
    if not articles_text:
        logger.warning(
            "rewrite_story skipped story_id=%s style=%s language=%s: no article text",
            story_id,
            style,
            language,
        )
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
    summary_sentences = processing.get("summary_sentences", 2)
    max_tokens = processing.get("rewrite_max_tokens", 4096)
    prompt_language = _get_language_label(config, language)

    prompt_template = load_prompt(prompt_name)
    body = prompt_template.format(
        articles_text=articles_text,
        language=prompt_language,
        summary_sentences=summary_sentences,
    )
    prompt = _REWRITE_OUTPUT_CONTRACT_PREFIX.format(language=prompt_language) + body

    if provider is None:
        provider = get_provider(config, task="rewrite")
    try:
        rw_temp = _llm_task_temperature(config, "rewrite")
        logger.debug(
            "rewrite_story: calling LLM story_id=%s style=%s language=%s",
            story_id,
            style,
            language,
        )
        response = provider.complete(prompt, max_tokens=max_tokens, temperature=rw_temp)
        try:
            title, summary, full_text = _parse_story_llm_response(response)
        except ValueError as ve:
            err_msg = str(ve)[:500]
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
            logger.warning(
                "rewrite_story failed story_id=%s style=%s language=%s: %s",
                story_id,
                style,
                language,
                err_msg,
            )
            return False
        title, summary, full_text = _proofread_if_enabled(
            provider,
            title,
            summary,
            full_text,
            prompt_language,
            config,
        )
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
        if is_ollama_connection_failure(e):
            raise RewriteBatchAbort(str(e)) from e
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
        logger.warning(
            "rewrite_story failed story_id=%s style=%s language=%s: %s",
            story_id,
            style,
            language,
            err_msg,
        )
        return False


def _simplify_rewrite(
    story_id: str,
    neutral_rewrite: dict[str, Any],
    config: dict[str, Any],
    provider: LLMProvider,
    base_language: str,
) -> bool:
    """Simplify a neutral rewrite in base_language to simple language in the same locale."""
    article_text = _build_article_text_from_rewrite(neutral_rewrite)
    processing = config.get("processing", {})
    summary_sentences = processing.get("summary_sentences", 2)
    max_tokens = processing.get("rewrite_max_tokens", 4096)
    prompt_language = _get_language_label(config, base_language)

    prompt_template = load_prompt("simplify_article")
    prompt = prompt_template.format(
        article_text=article_text,
        summary_sentences=summary_sentences,
        language=prompt_language,
    )

    try:
        sim_temp = _llm_task_temperature(config, "simplify")
        response = provider.complete(prompt, max_tokens=max_tokens, temperature=sim_temp)
        title, summary, full_text = _parse_story_llm_response(response)
        title, summary, full_text = _proofread_if_enabled(
            provider,
            title,
            summary,
            full_text,
            prompt_language,
            config,
        )
        db_stories.insert_story_rewrite(
            story_id=story_id,
            style="simple",
            language=base_language,
            title=title,
            summary=summary,
            full_text=full_text,
            rewrite_failed=False,
        )
        return True
    except Exception as e:
        if is_ollama_connection_failure(e):
            raise RewriteBatchAbort(str(e)) from e
        err_msg = str(e)[:500]
        db_stories.insert_story_rewrite(
            story_id=story_id,
            style="simple",
            language=base_language,
            title=None,
            summary=None,
            full_text=None,
            rewrite_failed=True,
            error_message=err_msg,
        )
        logger.warning("simplify_rewrite failed story_id=%s: %s", story_id, err_msg)
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
    summary_sentences = processing.get("summary_sentences", 2)
    max_tokens = processing.get("rewrite_max_tokens", 4096)

    writing_note_section = _writing_note_section_for_translate(config, target_lang_id)
    prompt_template = load_prompt("translate_article")
    prompt = prompt_template.format(
        article_text=article_text,
        target_language=target_language,
        style_description=style_description,
        summary_sentences=summary_sentences,
        writing_note_section=writing_note_section,
    )

    try:
        tr_temp = _llm_task_temperature(config, "translate")
        response = provider.complete(prompt, max_tokens=max_tokens, temperature=tr_temp)
        title, summary, full_text = _parse_story_llm_response(response)
        title, summary, full_text = _proofread_if_enabled(
            provider,
            title,
            summary,
            full_text,
            target_language,
            config,
        )
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
        if is_ollama_connection_failure(e):
            raise RewriteBatchAbort(str(e)) from e
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
        logger.warning(
            "translate_rewrite failed story_id=%s style=%s language=%s: %s",
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
    *,
    translation_max_workers: int = 1,
) -> tuple[int, int]:
    """Cascade: neutral in base_language, optional simplify for simple, then translate configured styles."""
    succeeded = 0
    failed = 0
    style_ids = _configured_style_ids(config)

    # Step 1: Neutral in base language (merge sources)
    neutral_key = ("neutral", base_language)
    has_valid_neutral = (
        neutral_key in existing_rewrites
        and bool(existing_rewrites[neutral_key].get("title"))
    )
    if not has_valid_neutral:
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

    # Step 2: Simple in base language (only when "simple" is a configured style)
    simple_key = ("simple", base_language)
    simple_rewrite: dict[str, Any] | None = None
    if "simple" in style_ids:
        if needs_full_regen or simple_key not in existing_rewrites:
            ok = _simplify_rewrite(
                story_id=story_id,
                neutral_rewrite=neutral_rewrite,
                config=config,
                provider=simplify_provider,
                base_language=base_language,
            )
            if not ok:
                failed += 1
            else:
                succeeded += 1
                all_rewrites = db_stories.get_all_rewrites_for_story(story_id)
                existing_rewrites[simple_key] = all_rewrites.get(simple_key, {})
        simple_rewrite = existing_rewrites.get(simple_key)

    # Step 3: Translate to other languages (parallel when translation_max_workers > 1)
    translation_jobs: list[tuple[str, str, dict[str, Any]]] = []
    for lang_id in other_languages:
        for style in style_ids:
            key = (style, lang_id)
            if not (needs_full_regen or key not in existing_rewrites):
                continue
            if style == "neutral":
                source = neutral_rewrite
            else:
                source = simple_rewrite or {}
            if not source or not source.get("title"):
                continue
            translation_jobs.append((style, lang_id, source))

    def _run_one_translation(job: tuple[str, str, dict[str, Any]]) -> bool:
        style_j, lang_j, source_j = job
        return _translate_rewrite(
            story_id=story_id,
            source_rewrite=source_j,
            style=style_j,
            target_lang_id=lang_j,
            config=config,
            provider=translate_provider,
        )

    if translation_jobs:
        tw = max(1, translation_max_workers)
        if tw <= 1 or len(translation_jobs) == 1:
            for job in translation_jobs:
                if _run_one_translation(job):
                    succeeded += 1
                else:
                    failed += 1
        else:
            max_workers = min(tw, len(translation_jobs))
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = [executor.submit(_run_one_translation, j) for j in translation_jobs]
                for fut in as_completed(futures):
                    if fut.result():
                        succeeded += 1
                    else:
                        failed += 1

    db_stories.set_story_last_rewrite_at(story_id)
    db_stories.set_story_needs_rewrite(story_id, False)
    return (succeeded, failed)


def _gather_rewrite_work(
    variants: list[tuple[str, str]],
    since: datetime | None,
    batch_size: int,
    cooldown_minutes: int = 0,
) -> list[tuple[str, list[dict[str, Any]], bool]]:
    """Return list of (story_id, articles, needs_full_regen) needing rewrite."""
    limit = None if batch_size <= 0 else batch_size
    stories = db_stories.get_stories_needing_any_rewrite(
        variants=variants,
        since=since,
        limit=limit,
        cooldown_minutes=cooldown_minutes,
    )
    if not stories:
        return []
    story_ids = [row["story_id"] for row in stories]
    articles_by_story = db_stories.get_articles_for_stories(story_ids)
    work: list[tuple[str, list[dict[str, Any]], bool]] = []
    for row in stories:
        story_id = row["story_id"]
        needs_rewrite = row.get("needs_rewrite", False)
        articles = articles_by_story.get(story_id, [])
        if articles:
            work.append((story_id, articles, needs_rewrite))
    return work


def _gather_rewrite_work_all_stories(
    since: datetime | None,
    batch_size: int,
) -> list[tuple[str, list[dict[str, Any]], bool]]:
    """Return (story_id, articles, True) for every story with articles (full cascade)."""
    limit = None if batch_size <= 0 else batch_size
    stories = db_stories.get_all_stories_with_articles(since=since, limit=limit)
    if not stories:
        return []
    story_ids = [row["story_id"] for row in stories]
    articles_by_story = db_stories.get_articles_for_stories(story_ids)
    work: list[tuple[str, list[dict[str, Any]], bool]] = []
    for row in stories:
        story_id = row["story_id"]
        articles = articles_by_story.get(story_id, [])
        if articles:
            work.append((story_id, articles, True))
    return work


def _execute_cascading_rewrites(
    work: list[tuple[str, list[dict[str, Any]], bool]],
    config: dict[str, Any],
    base_language: str,
    other_languages: list[str],
    rewrite_provider: LLMProvider,
    simplify_provider: LLMProvider,
    translate_provider: LLMProvider,
    *,
    parallel_workers: int | None = None,
    translation_max_workers: int | None = None,
) -> tuple[int, int]:
    """Run cascading rewrites for work items. Returns (succeeded, failed)."""
    if not work:
        return (0, 0)
    schedule_cfg = config.get("schedule", {})
    pw = parallel_workers
    if pw is None:
        pw = max(1, int(schedule_cfg.get("rewrite_parallel_workers") or 1))
    tw = translation_max_workers if translation_max_workers is not None else pw

    total = len(work)
    succeeded = 0
    failed = 0
    progress_state = {"done": 0, "frame": 0}
    ollama_host = _llm_host_for_logging(config)

    # Bulk-fetch all existing rewrites for all stories in this batch (avoids N+1)
    story_ids = [sid for sid, _, _ in work]
    all_existing = db_stories.get_all_rewrites_for_stories(story_ids)

    def _process_one(
        pack: tuple[int, str, list[dict[str, Any]], bool],
    ) -> tuple[int, str, int, int]:
        idx, story_id, articles, needs_full_regen = pack
        existing = all_existing.get(story_id, {})
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
            translation_max_workers=tw,
        )
        if pw > 1:
            with _rewrite_progress_lock:
                progress_state["done"] += 1
                progress_state["frame"] += 1
                tit = _rewrite_story_title_snippet(articles, story_id)
                _render_rewrite_progress(
                    progress_state["done"],
                    total,
                    tit,
                    frame=progress_state["frame"],
                )
        return (idx, story_id, s, f)

    with quiet_http_library_info_logs():
        try:
            if pw <= 1:
                for i, (story_id, articles, needs_full_regen) in enumerate(work, 1):
                    try:
                        pack = (i, story_id, articles, needs_full_regen)
                        _, _, s, f = _process_one(pack)
                    except RewriteBatchAbort as e:
                        remaining = max(0, total - i)
                        logger.warning(
                            "Ollama unreachable at %s (%s); stopping this rewrite run "
                            "(%d story(s) not processed). "
                            "Start Ollama or set llm.host / OLLAMA_HOST.",
                            ollama_host,
                            e,
                            remaining,
                        )
                        break
                    succeeded += s
                    failed += f
                    short_id = story_id[:12]
                    logger.debug(
                        "    [%d/%d] %s... %d ok, %d fail",
                        i,
                        total,
                        short_id,
                        s,
                        f,
                    )
                    _render_rewrite_progress(
                        i,
                        total,
                        _rewrite_story_title_snippet(articles, story_id),
                        frame=i - 1,
                    )
                return (succeeded, failed)

            packs = [(i, sid, arts, nr) for i, (sid, arts, nr) in enumerate(work, 1)]
            with ThreadPoolExecutor(max_workers=min(pw, len(work))) as executor:
                future_map = {executor.submit(_process_one, p): p for p in packs}
                for future in as_completed(future_map):
                    try:
                        idx, story_id, s, f = future.result()
                    except RewriteBatchAbort as e:
                        logger.warning(
                            "Ollama unreachable at %s (%s); stopping this rewrite run "
                            "(remaining parallel work may be incomplete). "
                            "Start Ollama or set llm.host / OLLAMA_HOST.",
                            ollama_host,
                            e,
                        )
                        break
                    succeeded += s
                    failed += f
                    short_id = story_id[:12]
                    logger.debug(
                        "    [%d/%d] %s... %d ok, %d fail (parallel)",
                        idx,
                        total,
                        short_id,
                        s,
                        f,
                    )
        finally:
            if sys.stderr.isatty() and total > 0:
                sys.stderr.write("\n")
                sys.stderr.flush()

    return (succeeded, failed)


def run_rewrite_batch(config: dict[str, Any]) -> RewriteReport:
    """Process stories via configured rewrite cascade (neutral; optional simplify; translate)."""
    style_ids = _configured_style_ids(config)
    processing = config.get("processing", {})
    window_hours = processing.get("cluster_window_hours", 24)
    since = (
        datetime.now(UTC) - timedelta(hours=window_hours)
        if window_hours
        else None
    )
    schedule_cfg = config.get("schedule", {})
    batch_size = int(schedule_cfg.get("rewrite_batch_size") or 0)
    cooldown_minutes = int(processing.get("rewrite_cooldown_minutes") or 0)

    variants = _get_rewriting_variants(config)
    base_language = config.get("rewriting", {}).get("base_language", "en")
    other_languages = [
        lang["id"]
        for lang in config.get("rewriting", {}).get("languages", [])
        if lang["id"] != base_language
    ]

    variant_str = ", ".join(f"{sty}/{lng}" for sty, lng in variants)
    batch_desc = "unlimited" if batch_size <= 0 else str(batch_size)

    work = _gather_rewrite_work(variants, since, batch_size, cooldown_minutes)
    if not work:
        logger.info(
            "Rewrite batch: no stories need rewrite (window_hours=%s, batch_size=%s)",
            window_hours if window_hours else "all",
            batch_desc,
        )
        return RewriteReport(
            variants_processed=len(variants),
            stories_attempted=0,
            stories_succeeded=0,
            stories_failed=0,
        )

    parallel_w = max(1, int(schedule_cfg.get("rewrite_parallel_workers") or 1))
    logger.info(
        "Rewrite batch: %d stories, workers=%d, base_language=%s, variants=%s",
        len(work),
        parallel_w,
        base_language,
        variant_str or "—",
    )
    rewrite_provider = get_provider(config, task="rewrite")
    if "simple" in style_ids:
        simplify_provider = get_provider(config, task="simplify")
    else:
        simplify_provider = rewrite_provider
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
    return RewriteReport(
        variants_processed=len(variants),
        stories_attempted=stories_attempted,
        stories_succeeded=stories_succeeded,
        stories_failed=stories_failed,
    )


def run_rewrite_all_stories(config: dict[str, Any]) -> RewriteReport:
    """Regenerate rewrites for every story with articles (ignores needs_rewrite / coverage).

    Uses the same time window and batch size as the scheduled rewrite job
    (``processing.cluster_window_hours``, ``schedule.rewrite_batch_size``).
    Intended for operators iterating on prompts or models.
    """
    style_ids = _configured_style_ids(config)
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

    variant_str = ", ".join(f"{sty}/{lng}" for sty, lng in variants)
    batch_desc = "unlimited" if batch_size <= 0 else str(batch_size)

    work = _gather_rewrite_work_all_stories(since, batch_size)
    if not work:
        logger.info(
            "Rewrite-all: no stories with articles (window_hours=%s, batch_size=%s)",
            window_hours if window_hours else "all",
            batch_desc,
        )
        return RewriteReport(
            variants_processed=len(variants),
            stories_attempted=0,
            stories_succeeded=0,
            stories_failed=0,
        )

    parallel_w = max(1, int(schedule_cfg.get("rewrite_parallel_workers") or 1))
    logger.info(
        "Rewrite-all: %d stories (full regen), workers=%d, base_language=%s, variants=%s",
        len(work),
        parallel_w,
        base_language,
        variant_str or "—",
    )
    rewrite_provider = get_provider(config, task="rewrite")
    if "simple" in style_ids:
        simplify_provider = get_provider(config, task="simplify")
    else:
        simplify_provider = rewrite_provider
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
    return RewriteReport(
        variants_processed=len(variants),
        stories_attempted=stories_attempted,
        stories_succeeded=stories_succeeded,
        stories_failed=stories_failed,
    )


# Backwards compatibility alias
rewrite_cluster = rewrite_story


