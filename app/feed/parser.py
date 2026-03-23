"""RSS/Atom feed parser and normalizer."""

import re
from datetime import UTC, datetime
from html import unescape
from typing import Any, TypedDict

import feedparser
from feedparser import FeedParserDict


class RawArticle(TypedDict):
    """Normalized article from a feed entry."""

    guid: str
    title: str
    url: str
    published_at: datetime | None
    raw_text: str
    full_text: str
    image_url: str | None
    image_source: str | None
    categories: list[str]


# Maps common Spanish/Catalan RSS category terms to canonical IDs.
# Aligned with existing topic IDs in config/sources.yaml.
_CATEGORY_NORMALIZE: dict[str, str] = {
    # Sports
    "deportes": "sports",
    "esports": "sports",
    "sport": "sports",
    "futbol": "sports",
    "fútbol": "sports",
    "liga": "sports",
    "champions": "sports",
    "tennis": "sports",
    "basquet": "sports",
    "bàsquet": "sports",
    "basquetbol": "sports",
    "bàsquetbol": "sports",
    "basket": "sports",
    "atletisme": "sports",
    "atletismo": "sports",
    "ciclisme": "sports",
    "ciclismo": "sports",
    "motociclisme": "sports",
    "motociclismo": "sports",
    "formula 1": "sports",
    "fórmula 1": "sports",
    "formula1": "sports",
    # Politics
    "politica": "politics",
    "política": "politics",
    "nacional": "politics",
    "espanya": "politics",
    "espana": "politics",
    "catalunya": "politics",
    "cataluña": "politics",
    "eleccions": "politics",
    "elecciones": "politics",
    "parlament": "politics",
    "congreso": "politics",
    "senado": "politics",
    "govern": "politics",
    "gobierno": "politics",
    # International
    "internacional": "international",
    "mundo": "international",
    "món": "international",
    "mon": "international",
    "europa": "international",
    "ue": "international",
    "onu": "international",
    "guerra": "international",
    "conflicte": "international",
    "conflicto": "international",
    # Society
    "societat": "society",
    "sociedad": "society",
    "salut": "society",
    "salud": "society",
    "sanitat": "society",
    "sanidad": "society",
    "educacio": "society",
    "educación": "society",
    "treball": "society",
    "trabajo": "society",
    "immigracio": "society",
    "inmigración": "society",
    "immigració": "society",
    "justicia": "society",
    "seguretat": "society",
    "seguridad": "society",
    "violencia": "society",
    "feminisme": "society",
    "feminismo": "society",
    "lgbt": "society",
    "drets": "society",
    "derechos": "society",
    # Culture
    "cultura": "culture",
    "arts": "culture",
    "art": "culture",
    "musica": "culture",
    "música": "culture",
    "cinema": "culture",
    "teatre": "culture",
    "teatro": "culture",
    "llibres": "culture",
    "libros": "culture",
    "literatura": "culture",
    "televisio": "culture",
    "televisión": "culture",
    "entreteniment": "culture",
    "entretenimiento": "culture",
    "gastronomia": "culture",
    "gastronomía": "culture",
    # Economy
    "economia": "economy",
    "economía": "economy",
    "negocis": "economy",
    "negocios": "economy",
    "empresas": "economy",
    "empreses": "economy",
    "borsa": "economy",
    "bolsa": "economy",
    "mercats": "economy",
    "mercados": "economy",
    "finances": "economy",
    "finanzas": "economy",
    "banca": "economy",
    "laboral": "economy",
    # Science
    "ciencia": "science",
    "ciència": "science",
    "ciències": "science",
    "ciencias": "science",
    "tecnologia": "technology",
    "tecnología": "technology",
    "innovacio": "technology",
    "innovación": "technology",
    "digital": "technology",
    "internet": "technology",
    "robotica": "technology",
    "robótica": "technology",
    "inteligencia artificial": "technology",
    "ia": "technology",
    # Environment
    "medi ambient": "environment",
    "medio ambiente": "environment",
    "clima": "environment",
    "climàtic": "environment",
    "climático": "environment",
    "sostenibilitat": "environment",
    "sostenibilidad": "environment",
    "energia": "environment",
    "energía": "environment",
    "natura": "environment",
    "naturaleza": "environment",
    "biodiversitat": "environment",
    "biodiversidad": "environment",
    # General
    "general": "general",
    "portada": "general",
    "noticies": "general",
    "noticias": "general",
    "actualitat": "general",
    "actualidad": "general",
    "última hora": "general",
    "ultima hora": "general",
    "últimes": "general",
    "ultimes": "general",
}


def _strip_html(html: str) -> str:
    """Remove HTML tags and decode entities. Simple implementation."""
    if not html:
        return ""
    text = re.sub(r"<[^>]+>", " ", html)
    return unescape(text).strip()


def _parse_date(entry: FeedParserDict) -> datetime | None:
    """Extract published/updated date from entry."""
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if parsed:
        return datetime(
            parsed[0], parsed[1], parsed[2], parsed[3], parsed[4], parsed[5],
            tzinfo=UTC,
        )
    return None


def _get_guid(entry: FeedParserDict) -> str:
    """Extract guid or fall back to link."""
    guid = entry.get("guid") or entry.get("id")
    if isinstance(guid, str):
        return guid
    if hasattr(guid, "get") and isinstance(guid, dict):
        return str(guid.get("guid", "") or entry.get("link", ""))
    return str(entry.get("link", ""))


def _get_url(entry: FeedParserDict) -> str:
    """Extract canonical URL from entry."""
    link = entry.get("link")
    if link:
        return str(link)
    guid = entry.get("guid") or entry.get("id")
    if isinstance(guid, str) and guid.startswith(("http://", "https://")):
        return guid
    return ""


def _get_raw_text(entry: FeedParserDict) -> str:
    """Extract summary/description as raw text."""
    summary = entry.get("summary") or entry.get("description")
    if not summary:
        return ""
    if isinstance(summary, str):
        return _strip_html(summary)
    if hasattr(summary, "get") and isinstance(summary, dict):
        return _strip_html(str(summary.get("value", "")))
    return ""


def _get_full_text(entry: FeedParserDict) -> str:
    """Extract full content from content:encoded or content block."""
    content = entry.get("content")
    if not content or not isinstance(content, list):
        return ""
    parts: list[str] = []
    for block in content:
        if isinstance(block, dict) and "value" in block:
            val = block["value"]
            if isinstance(val, str):
                parts.append(_strip_html(val))
    return "\n\n".join(parts) if parts else ""


_IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg")


def _is_image_url(url: str) -> bool:
    """Return True if URL looks like an image."""
    if not url or not isinstance(url, str):
        return False
    lower = url.lower().split("?")[0]
    return lower.endswith(_IMAGE_EXTENSIONS)


def _get_image_url(entry: FeedParserDict) -> tuple[str | None, str | None]:
    """Extract best image URL from feed entry.

    Checks in order: media_content, enclosures, first <img> in item content HTML,
    then media_thumbnail (often a generic or unrelated promo thumb).

    Returns (image_url, image_source) or (None, None).
    """
    # 1. media_content — list of dicts with url, medium, type, width, height
    media_content = entry.get("media_content")
    if media_content and isinstance(media_content, list):
        candidates: list[tuple[str, int]] = []
        for item in media_content:
            if not isinstance(item, dict):
                continue
            url = item.get("url") or item.get("href")
            if not url:
                continue
            medium = (item.get("medium") or "").lower()
            mime = (item.get("type") or "").lower()
            if medium == "image" or mime.startswith("image/") or _is_image_url(str(url)):
                width = item.get("width")
                try:
                    w = int(width) if width is not None else 0
                except (ValueError, TypeError):
                    w = 0
                candidates.append((str(url), w))
        if candidates:
            candidates.sort(key=lambda x: x[1], reverse=True)
            return (candidates[0][0], "media_content")

    # 2. enclosures — href, type
    enclosures = entry.get("enclosures")
    if enclosures and isinstance(enclosures, list):
        for enc in enclosures:
            if not isinstance(enc, dict):
                continue
            url = enc.get("href") or enc.get("url")
            mime = (enc.get("type") or "").lower()
            if url and (mime.startswith("image/") or _is_image_url(str(url))):
                return (str(url), "enclosure")

    # 3. First <img src="..."> in content HTML (usually the article lead in fulltext feeds)
    content = entry.get("content")
    if content and isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and "value" in block:
                val = block["value"]
                if isinstance(val, str):
                    match = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', val, re.I)
                    if match:
                        return (match.group(1).strip(), "content_html")

    # 4. media_thumbnail — last: frequently unrelated to the linked story
    media_thumbnail = entry.get("media_thumbnail")
    if media_thumbnail and isinstance(media_thumbnail, list):
        thumb_candidates: list[tuple[str, int]] = []
        for item in media_thumbnail:
            if not isinstance(item, dict):
                continue
            url = item.get("url") or item.get("href")
            if not url:
                continue
            width = item.get("width")
            try:
                w = int(width) if width is not None else 0
            except (ValueError, TypeError):
                w = 0
            thumb_candidates.append((str(url), w))
        if thumb_candidates:
            thumb_candidates.sort(key=lambda x: x[1], reverse=True)
            return (thumb_candidates[0][0], "media_thumbnail")

    return (None, None)


def _normalize_category(term: str) -> str:
    """Map RSS category term to canonical ID. Unmapped terms pass through lowercased."""
    if not term or not isinstance(term, str):
        return ""
    key = term.strip().lower()
    if not key:
        return ""
    return _CATEGORY_NORMALIZE.get(key, key)


def _get_categories(entry: FeedParserDict) -> list[str]:
    """Extract and normalize category terms from entry.tags. Deduplicated."""
    tags = entry.get("tags")
    if not tags or not isinstance(tags, list):
        return []
    seen: set[str] = set()
    result: list[str] = []
    for tag in tags:
        if not isinstance(tag, dict):
            continue
        term = tag.get("term") or tag.get("label")
        if term is None:
            continue
        normalized = _normalize_category(str(term))
        if normalized and normalized not in seen:
            seen.add(normalized)
            result.append(normalized)
    return result


def parse_feed(content: bytes) -> list[dict[str, Any]]:
    """Parse RSS/Atom feed content into normalized RawArticle dicts.

    Each dict has: guid, title, url, published_at, raw_text, full_text,
    image_url, image_source.
    """
    parsed = feedparser.parse(content)
    entries = parsed.get("entries", [])
    result: list[dict[str, Any]] = []

    for entry in entries:
        url = _get_url(entry)
        if not url:
            continue

        title = entry.get("title") or "(No title)"
        if not isinstance(title, str):
            title = str(title)

        image_url, image_source = _get_image_url(entry)

        result.append(
            {
                "guid": _get_guid(entry),
                "title": title,
                "url": url,
                "published_at": _parse_date(entry),
                "raw_text": _get_raw_text(entry),
                "full_text": _get_full_text(entry),
                "image_url": image_url,
                "image_source": image_source,
                "categories": _get_categories(entry),
            }
        )

    return result
