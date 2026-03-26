"""Detect native advertising / sponsored RSS items for feed exclusion."""

from __future__ import annotations

import html
import re
import unicodedata
from typing import Any

_TAG_RE = re.compile(r"<[^>]+>")


def _strip_accents(s: str) -> str:
    nkfd = unicodedata.normalize("NFKD", s)
    return "".join(c for c in nkfd if not unicodedata.combining(c))


def _normalize_for_match(s: str) -> str:
    """Lowercase, strip accents, collapse whitespace for substring checks."""
    if not s:
        return ""
    unescaped = html.unescape(s)
    without_tags = _TAG_RE.sub(" ", unescaped)
    folded = _strip_accents(without_tags.lower())
    return re.sub(r"\s+", " ", folded).strip()


def _promoted_config(config: dict[str, Any]) -> dict[str, Any]:
    feed = config.get("feed") or {}
    return feed.get("promoted_content") or {}


def article_looks_promoted(article: dict[str, Any], config: dict[str, Any]) -> bool:
    """True if title or body lead matches a configured sponsored pattern."""
    pc = _promoted_config(config)
    if not pc.get("enabled", True):
        return False
    patterns = pc.get("patterns") or []
    norm_patterns = [_normalize_for_match(p) for p in patterns if isinstance(p, str) and p.strip()]
    if not norm_patterns:
        return False
    prefix_len = int(pc.get("body_prefix_chars", 400))
    title = article.get("title") or ""
    raw = article.get("raw_text") or ""
    full = article.get("full_text") or ""
    body = raw if raw.strip() else full
    body_lead = body[:prefix_len] if body else ""
    hay = _normalize_for_match(f"{title}\n{body_lead}")
    if not hay:
        return False
    return any(p in hay for p in norm_patterns)


def exclude_promoted_articles(
    articles: list[dict[str, Any]],
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    """Drop articles that look like paid / sponsored placements."""
    if not articles:
        return articles
    pc = _promoted_config(config)
    if not pc.get("enabled", True):
        return articles
    return [a for a in articles if not article_looks_promoted(a, config)]
