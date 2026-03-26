"""Highlight pass: wraps named entities / key terms in ** in story full_text.

Two modes (processing.highlight_method):
  "ner"  (default) — spaCy xx_ent_wiki_sm; falls back to regex. Zero LLM calls.
  "llm"            — original Ollama pass; use when maximum quality matters.
"""

import logging
import re
import shutil
import sys
from dataclasses import dataclass
from typing import Any

from app.db import stories as db_stories

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


# --- NER path ---------------------------------------------------------------

_SPACY_NLP: Any = None  # module-level cache to avoid reloading per article
_SPACY_LOAD_ATTEMPTED = False
_NER_ENTITY_LABELS = frozenset({"PERSON", "ORG", "GPE", "LOC"})


def _load_spacy() -> Any | None:
    """Load spaCy xx_ent_wiki_sm model once. Returns NLP object or None."""
    global _SPACY_NLP, _SPACY_LOAD_ATTEMPTED
    if _SPACY_LOAD_ATTEMPTED:
        return _SPACY_NLP
    _SPACY_LOAD_ATTEMPTED = True
    try:
        import spacy  # type: ignore[import]

        _SPACY_NLP = spacy.load("xx_ent_wiki_sm")
        logger.info("highlight: loaded spaCy xx_ent_wiki_sm")
    except Exception as e:
        logger.info("highlight: spaCy not available (%s), using regex fallback", e)
        _SPACY_NLP = None
    return _SPACY_NLP


def _highlight_ner_regex(full_text: str) -> str:
    """Regex fallback: bold 2+ consecutive Title Case words not already bolded
    (first occurrence only)."""
    # Matches two or more consecutive words starting with an uppercase letter.
    # Negative lookbehind/lookahead prevents double-wrapping.
    pattern = re.compile(r"(?<!\*)\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b(?!\*)")
    seen: set[str] = set()

    def _replace(m: re.Match[str]) -> str:
        key = m.group(1).lower()
        if key in seen:
            return m.group(1)
        seen.add(key)
        return f"**{m.group(1)}**"

    return pattern.sub(_replace, full_text)


def _highlight_ner_spacy(full_text: str) -> str:
    """Bold PERSON/ORG/GPE/LOC entities using spaCy; fall back to regex."""
    nlp = _load_spacy()
    if nlp is None:
        return _highlight_ner_regex(full_text)

    try:
        doc = nlp(full_text[:50_000])  # guard against very long texts
    except Exception as e:
        logger.warning("highlight: spaCy processing failed (%s), using regex fallback", e)
        return _highlight_ner_regex(full_text)

    # Collect spans, remove overlaps, sort
    spans: list[tuple[int, int]] = []
    for ent in doc.ents:
        if ent.label_ in _NER_ENTITY_LABELS and ent.text.strip():
            spans.append((ent.start_char, ent.end_char))

    if not spans:
        return full_text

    spans.sort()
    # Remove overlapping spans (keep first of each overlapping group)
    clean: list[tuple[int, int]] = []
    for s, e in spans:
        if clean and s < clean[-1][1]:
            continue
        clean.append((s, e))

    # Deduplicate: bold each distinct entity text only once (first occurrence)
    seen: set[str] = set()
    unique: list[tuple[int, int]] = []
    for s, e in clean:
        key = full_text[s:e].strip().lower()
        if key and key not in seen:
            seen.add(key)
            unique.append((s, e))

    # Insert markers from end to avoid offset shifts
    chars = list(full_text)
    for s, e in reversed(unique):
        chars[s:e] = list(f"**{full_text[s:e]}**")
    return "".join(chars)


# --- Dispatch ----------------------------------------------------------------


def highlight_story(
    story_id: str,
    full_text: str,
    style: str,
    language: str,
    config: dict[str, Any],
    *,
    provider: Any = None,  # only used for highlight_method="llm"
) -> bool:
    """Highlight significant terms in full_text and store the result.

    Dispatches to NER (default) or LLM depending on processing.highlight_method.
    Returns True on success.
    """
    processing = config.get("processing", {})
    method = str(processing.get("highlight_method", "ner")).lower()

    if method == "ner":
        try:
            highlighted = _highlight_ner_spacy(full_text)
            if not highlighted:
                logger.warning(
                    "highlight_story(ner): empty result for story_id=%s style=%s language=%s",
                    story_id,
                    style,
                    language,
                )
                return False
            db_stories.update_story_rewrite_highlight(story_id, style, language, highlighted)
            logger.debug(
                "highlight_story(ner): done story_id=%s style=%s language=%s",
                story_id,
                style,
                language,
            )
            return True
        except Exception as e:
            logger.warning(
                "highlight_story(ner) failed story_id=%s style=%s language=%s: %s",
                story_id,
                style,
                language,
                e,
            )
            return False

    # LLM path (highlight_method="llm")
    from app.llm.prompts import load_prompt
    from app.llm.provider import get_provider

    if provider is None:
        provider = get_provider(config, task="highlight")

    max_tokens = int(processing.get("rewrite_max_tokens") or 4096)
    prompt_template = load_prompt("highlight_terms")
    prompt = prompt_template.format(full_text=full_text)

    try:
        response = provider.complete(prompt, max_tokens=max_tokens, temperature=0.0)
        highlighted = response.strip()
        if not highlighted:
            logger.warning(
                "highlight_story(llm): empty response for story_id=%s style=%s language=%s",
                story_id,
                style,
                language,
            )
            return False
        db_stories.update_story_rewrite_highlight(story_id, style, language, highlighted)
        logger.debug(
            "highlight_story(llm): done story_id=%s style=%s language=%s",
            story_id,
            style,
            language,
        )
        return True
    except Exception as e:
        logger.warning(
            "highlight_story(llm) failed story_id=%s style=%s language=%s: %s",
            story_id,
            style,
            language,
            e,
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
    processing = config.get("processing", {})
    method = str(processing.get("highlight_method", "ner")).lower()
    logger.info("Highlight starting: %d story rewrites pending (method=%s)", total, method)

    # LLM provider only needed when method="llm"
    llm_provider = None
    if method == "llm":
        from app.llm.provider import get_provider

        llm_provider = get_provider(config, task="highlight")

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
                provider=llm_provider,
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
        "Highlight complete: %d succeeded, %d failed (method=%s)",
        succeeded,
        failed,
        method,
    )
    return HighlightReport(attempted=attempted, succeeded=succeeded, failed=failed)
