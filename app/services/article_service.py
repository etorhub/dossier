"""Article feed and expansion logic. Feed shows stories, not individual articles."""

from datetime import UTC, datetime, timedelta
from typing import Any

from app.config import load_config, load_sources
from app.db import stories as db_stories
from app.services import profile_service
from app.services.promoted_content_service import exclude_promoted_articles
from app.services.scoring_service import score_story

_IMAGE_SOURCE_SCORES: dict[str, float] = {
    "article_body": 5.0,
    "media_content": 3.0,
    "enclosure": 2.5,
    "media_thumbnail": 2.0,
    "content_html": 1.5,
    "og_image": 1.0,
}
# Fallback for newly incorporated images with unknown or missing image_source
_IMAGE_SOURCE_FALLBACK = 0.5


def select_story_image(
    articles: list[dict[str, Any]],
    sources_map: dict[str, dict[str, Any]],
) -> tuple[str | None, str | None]:
    """Select best image URL from story articles.

    Returns (image_url, image_source_name). image_source_name is the publisher name
    for legal attribution; None when no image or source unknown.

    Scoring: image_source priority (article_body highest, then media_content,
    enclosure, media_thumbnail, content_html, og_image), then source quality_score
    as bonus, then earliest
    published_at as tiebreaker. Images with unknown image_source use fallback score
    so newly incorporated images are still displayed.
    """
    candidates: list[tuple[str, str | None, float, datetime | None]] = []
    for art in articles:
        url = art.get("image_url")
        if not url or not isinstance(url, str) or not url.strip():
            continue
        src = art.get("image_source") or ""
        base_score = _IMAGE_SOURCE_SCORES.get(src, _IMAGE_SOURCE_FALLBACK)
        quality = 0.0
        sid = art.get("source_id")
        source_name: str | None = None
        if sid and sources_map:
            src_info = sources_map.get(sid, {})
            source_name = src_info.get("name") or sid
            qs = src_info.get("quality_score")
            if qs is not None:
                try:
                    val = float(qs)
                    quality = val / 100.0 if val > 1 else val
                except (ValueError, TypeError):
                    pass
        total = base_score + quality
        pub = art.get("published_at")
        candidates.append((url, source_name, total, pub))

    if not candidates:
        return (None, None)

    def _sort_key(
        item: tuple[str, str | None, float, datetime | None],
    ) -> tuple[float, float]:
        _url, _sn, score, pub = item
        pub_ts = pub.timestamp() if pub else 0.0
        return (-score, pub_ts)

    candidates.sort(key=_sort_key)
    url, source_name = candidates[0][0], candidates[0][1]
    return (url, source_name)


# Backwards compatibility alias
select_cluster_image = select_story_image


def _get_rewrite_with_fallback(
    story_ids: list[str],
    style: str,
    language: str,
    config: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Get rewrites for story_ids. Fall back to default variant if primary missing."""
    rewrites = db_stories.get_story_rewrites(story_ids, style, language)
    rewriting = config.get("rewriting", {})
    default_style = rewriting.get("default_style", "neutral")
    default_language = rewriting.get("default_language", "ca")

    missing = [
        sid for sid in story_ids if sid not in rewrites or not rewrites[sid].get("full_text")
    ]
    if missing and (default_style != style or default_language != language):
        fallback = db_stories.get_story_rewrites(missing, default_style, default_language)
        for sid, rw in fallback.items():
            if rw.get("full_text"):
                rewrites[sid] = rw
    return rewrites


def get_feed(
    user_id: int,
) -> tuple[list[dict[str, Any]], bool]:
    """Return today's stories for the user, filtered by catalog topic overlap.

    Returns (feed, rewrites_pending). rewrites_pending is True when there are
    stories matching the user's profile but no rewrites yet (e.g. after setup).
    Each feed item has: id (story_id), title, summary, full_text, sources (list
    of {source_name, url, title}), relevance_score. Uses story_rewrites.
    Only stories with at least 2 distinct sources are shown (canonical stories).
    """
    profile = profile_service.get_profile_with_selections(user_id)
    if not profile:
        return ([], False)
    topic_ids = set(profile.get("topic_ids", []))
    if not topic_ids:
        return ([], False)

    sources = {s["id"]: s for s in load_sources()}
    config = load_config()
    style, language = profile_service.get_reading_variant(profile, config)
    processing = config.get("processing", {})
    window_hours = processing.get("cluster_window_hours", 24)
    limit = processing.get("articles_per_day", 10)
    min_sources = config.get("relevance", {}).get("min_sources", 2)

    since: datetime | None = (
        datetime.now(UTC) - timedelta(hours=window_hours) if window_hours else None
    )
    story_rows = db_stories.get_stories_with_articles_in_window(since)
    # Filter stories: keep only if >=1 article's source overlaps user topics
    # AND story has at least min_sources distinct sources (canonical stories)
    visible_stories: list[dict[str, Any]] = []
    for row in story_rows:
        story_id = row["story_id"]
        articles = exclude_promoted_articles(db_stories.get_articles_in_story(story_id), config)
        distinct_sources = len({a["source_id"] for a in articles})
        if distinct_sources < min_sources:
            continue
        for art in articles:
            sid = art["source_id"]
            src = sources.get(sid, {})
            src_topics = set(src.get("topics", []))
            if topic_ids & src_topics:
                visible_stories.append({"story_id": story_id, "articles": articles})
                break

    # Score each story (non-behavioral signals only; see scoring_service)
    for s in visible_stories:
        s["relevance_score"] = score_story(s, topic_ids, sources, config)
        pubs = [a["published_at"] for a in s["articles"] if a.get("published_at")]
        s["max_published_at"] = max(pubs) if pubs else None

    def _story_sort_key(row: dict[str, Any]) -> tuple[int, float, str]:
        """Primary: recency bucket (most recent first). Secondary: relevance_score desc."""
        bucket_hours = config.get("relevance", {}).get("recency_bucket_hours", 6)
        pub = row.get("max_published_at")
        if pub:
            if pub.tzinfo is None:
                pub = pub.replace(tzinfo=UTC)
            bucket = -int(pub.timestamp() // (bucket_hours * 3600))
        else:
            bucket = 0
        return (bucket, -row["relevance_score"], row["story_id"])

    # Partition by source count: multi-source first, singletons as backfill
    primary: list[dict[str, Any]] = []
    fallback: list[dict[str, Any]] = []
    for s in visible_stories:
        distinct = len({a["source_id"] for a in s["articles"]})
        if distinct >= min_sources:
            primary.append(s)
        else:
            fallback.append(s)

    primary.sort(key=_story_sort_key)
    fallback.sort(key=_story_sort_key)
    combined = primary + fallback
    visible_stories = combined[:limit] if limit else combined

    story_ids = [s["story_id"] for s in visible_stories]
    rewrites_map = _get_rewrite_with_fallback(story_ids, style, language, config)

    result: list[dict[str, Any]] = []
    for story_data in visible_stories:
        story_id = story_data["story_id"]
        articles = story_data["articles"]

        rw = rewrites_map.get(story_id)

        # Only show stories that have an LLM rewrite; never show raw source content
        if not rw or not rw.get("title") or not rw.get("full_text"):
            continue

        image_url, image_source_name = select_story_image(articles, sources)
        published_at = max(
            (a["published_at"] for a in articles if a.get("published_at")),
            default=None,
        )
        sources_count = len(articles)

        result.append(
            {
                "id": story_id,
                "title": rw["title"],
                "summary": rw.get("summary") or "",
                "full_text": rw["full_text"],
                "relevance_score": story_data.get("relevance_score"),
                "image_url": image_url,
                "image_source_name": image_source_name,
                "published_at": published_at,
                "sources_count": sources_count,
            }
        )
    rewrites_pending = len(visible_stories) > 0 and len(result) == 0
    return (result, rewrites_pending)


def get_expanded_story(
    story_id: str,
    style: str,
    language: str,
    config: dict[str, Any],
) -> dict[str, Any] | None:
    """Return story with full rewritten text for expansion. None if not found."""
    if not db_stories.story_exists(story_id):
        return None
    articles = exclude_promoted_articles(db_stories.get_articles_in_story(story_id), config)
    if not articles:
        return None
    rewrites_map = _get_rewrite_with_fallback([story_id], style, language, config)
    rw = rewrites_map.get(story_id)
    sources_map = {s["id"]: s for s in load_sources()}

    image_url, image_source_name = select_story_image(articles, sources_map)
    published_at = max(
        (a["published_at"] for a in articles if a.get("published_at")),
        default=None,
    )
    sources_count = len(articles)

    # Never show raw source content; use rewrite or "being prepared" placeholder
    if rw and rw.get("full_text"):
        title = rw.get("title") or "Article"
        summary = rw.get("summary") or ""
        full_text = rw["full_text"]
        highlighted_full_text = rw.get("highlighted_full_text")
    else:
        title = "Article"
        summary = ""
        full_text = "This article is being prepared. Please try again shortly."
        highlighted_full_text = None

    return {
        "id": story_id,
        "title": title,
        "summary": summary,
        "full_text": full_text,
        "highlighted_full_text": highlighted_full_text,
        "image_url": image_url,
        "image_source_name": image_source_name,
        "published_at": published_at,
        "sources_count": sources_count,
    }
