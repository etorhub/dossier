"""Assign articles to stories by embedding similarity. Global grouping, same for all users."""

import json
import logging
import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from app.config import load_config
from app.db import articles as db_articles
from app.db import stories as db_stories
from app.llm.embeddings import EmbeddingProviderError, get_embedding_provider
from app.llm.http_utils import is_ollama_connection_failure

logger = logging.getLogger(__name__)


@dataclass
class StoryReport:
    """Summary of a story assignment run."""

    articles_embedded: int
    articles_clustered: int
    stories_created: int


def _embedding_from_article(article: dict[str, Any]) -> list[float] | None:
    """Extract embedding from article. Returns None if invalid."""
    emb = article.get("embedding")
    if emb is None:
        return None
    if isinstance(emb, list):
        if len(emb) == 0:
            return None
        return emb
    if isinstance(emb, str):
        try:
            return json.loads(emb)
        except json.JSONDecodeError:
            return None
    return None


def _text_to_embed(article: dict[str, Any]) -> str:
    """Build text for embedding: title + content excerpt."""
    title = (article.get("title") or "").strip()
    full = (article.get("full_text") or "").strip()
    raw = (article.get("raw_text") or "").strip()
    content = full or raw
    content = content[:2000] if content else ""
    return f"{title} {content}".strip() or ""


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two vectors."""
    if len(a) != len(b) or len(a) == 0:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _compute_centroid(embeddings: list[list[float]]) -> list[float] | None:
    """Compute mean of embeddings. Returns None if empty or invalid."""
    valid = [e for e in embeddings if e and len(e) > 0]
    if not valid or not all(len(emb) == len(valid[0]) for emb in valid):
        return None
    n = len(valid)
    dim = len(valid[0])
    centroid = [sum(emb[i] for emb in valid) / n for i in range(dim)]
    return centroid


def _assign_to_existing_stories(
    articles: list[dict[str, Any]],
    existing_stories: list[dict[str, Any]],
    threshold: float,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Try to assign articles to existing stories by centroid similarity.

    Returns (assigned_count, remaining_articles). assigned_count is number of
    articles successfully assigned. remaining_articles are those not assigned.
    """
    assigned: list[tuple[str, str]] = []  # (article_id, story_id)
    remaining = []
    story_centroids: dict[str, list[float]] = {}
    for s in existing_stories:
        emb = s.get("centroid_embedding")
        if emb and isinstance(emb, list):
            story_centroids[s["story_id"]] = emb

    for art in articles:
        emb = _embedding_from_article(art)
        if not emb or art["id"] in {a for a, _ in assigned}:
            remaining.append(art)
            continue
        best_story_id: str | None = None
        best_sim = -1.0
        for sid, centroid in story_centroids.items():
            if not centroid:
                continue
            sim = _cosine_similarity(emb, centroid)
            if sim >= threshold and sim > best_sim:
                best_sim = sim
                best_story_id = sid
        if best_story_id:
            assigned.append((art["id"], best_story_id))
        else:
            remaining.append(art)

    return assigned, remaining


def _update_story_centroid(story_id: str) -> None:
    """Recompute and store centroid for story from its articles' embeddings."""
    articles = db_stories.get_articles_in_story(story_id)
    embeddings_raw = [_embedding_from_article(a) for a in articles]
    embeddings: list[list[float]] = [e for e in embeddings_raw if e is not None]
    if embeddings:
        centroid = _compute_centroid(embeddings)
        if centroid:
            db_stories.update_story_centroid(story_id, centroid)


def _cluster_articles(
    articles: list[dict[str, Any]],
    threshold: float,
) -> list[list[str]]:
    """Group articles by embedding similarity using complete-linkage clustering.

    Two groups merge only if every cross-group pair of articles has similarity >= threshold.
    Prevents chaining: unrelated articles are not grouped via a transitive chain.
    Returns list of groups (each = list of article_ids).
    """
    if not articles:
        return []
    n = len(articles)
    ids = [a["id"] for a in articles]
    embeddings = [_embedding_from_article(a) for a in articles]

    valid_indices = [i for i in range(n) if embeddings[i] is not None]
    invalid_indices = [i for i in range(n) if embeddings[i] is None]

    # Build pairwise similarity matrix (upper triangle)
    sim: dict[tuple[int, int], float] = {}
    for i in valid_indices:
        for j in valid_indices:
            if i < j:
                sim[(i, j)] = _cosine_similarity(embeddings[i], embeddings[j])

    # Start with each valid article as its own group
    groups: list[set[int]] = [{i} for i in valid_indices]

    # Complete-linkage: merge only when ALL cross-group pairs meet threshold
    merged = True
    while merged:
        merged = False
        best_min_sim = -1.0
        best_pair: tuple[int, int] | None = None

        for gi in range(len(groups)):
            for gj in range(gi + 1, len(groups)):
                g1, g2 = groups[gi], groups[gj]
                min_sim = 1.0
                for a in g1:
                    for b in g2:
                        key = (a, b) if a < b else (b, a)
                        min_sim = min(min_sim, sim.get(key, 0.0))
                if min_sim >= threshold and min_sim > best_min_sim:
                    best_min_sim = min_sim
                    best_pair = (gi, gj)

        if best_pair is not None:
            gi, gj = best_pair
            groups[gi].update(groups[gj])
            groups.pop(gj)
            merged = True

    # Convert to list of article_id lists; add singletons for articles without embeddings
    result = [[ids[i] for i in g] for g in groups]
    for i in invalid_indices:
        result.append([ids[i]])
    return result


def run_cluster_and_embed(config: dict[str, Any] | None = None) -> StoryReport:
    """Embed articles without embeddings, then assign unassigned articles to stories, create stories.

    Only creates stories for groups with at least 2 distinct sources.
    Single-source groups are skipped (wait for second source).
    """
    cfg = config or load_config()
    processing = cfg.get("processing", {})
    window_hours = processing.get("cluster_window_hours", 24)
    threshold = processing.get("story_similarity_threshold", processing.get("cluster_similarity_threshold", 0.90))
    embed_n = int(processing.get("embed_batch_size") or 0)
    embed_limit: int | None = None if embed_n <= 0 else embed_n
    min_sources = processing.get("story_min_sources", 2)

    # window_hours=0 means no time filter (same semantics as rewrite when window is 0)
    since: datetime | None = (
        datetime.now(UTC) - timedelta(hours=window_hours) if window_hours else None
    )
    report = StoryReport(articles_embedded=0, articles_clustered=0, stories_created=0)

    # 1. Embed articles without embeddings
    has_embedding_provider = True
    try:
        provider = get_embedding_provider(cfg)
    except EmbeddingProviderError as e:
        logger.warning("Embedding provider unavailable: %s. Using singleton stories.", e)
        has_embedding_provider = False
    else:
        emb_cfg = cfg.get("embeddings", {})
        ollama_host = (
            emb_cfg.get("host")
            or os.environ.get("OLLAMA_HOST")
            or "http://ollama:11434"
        )
        to_embed = db_articles.get_recent_articles_without_embedding(since, limit=embed_limit)
        for i, article in enumerate(to_embed):
            text = _text_to_embed(article)
            if not text:
                continue
            try:
                embedding = provider.embed(text)
                db_articles.update_article_embedding(article["id"], embedding)
                report.articles_embedded += 1
            except EmbeddingProviderError as e:
                if is_ollama_connection_failure(e):
                    deferred = max(0, len(to_embed) - i)
                    logger.warning(
                        "Ollama unreachable at %s (%s); stopping this embed run "
                        "(%d article(s) deferred). Start Ollama or set embeddings.host / OLLAMA_HOST.",
                        ollama_host,
                        e,
                        deferred,
                    )
                    break
                logger.warning("Embed failed for article %s: %s", article["id"], e)

    # 2. Get articles not yet in a story
    if has_embedding_provider:
        to_cluster = db_articles.get_articles_with_embedding_not_in_story(since)
    else:
        to_cluster = db_articles.get_articles_not_in_story(since)
    if not to_cluster:
        return report

    report.articles_clustered = len(to_cluster)

    # 2b. Backfill centroids for existing stories that don't have one
    if has_embedding_provider:
        story_rows = db_stories.get_stories_with_articles_in_window(since)
        for row in story_rows:
            sid = row["story_id"]
            if not db_stories.get_story_centroid(sid):
                _update_story_centroid(sid)

    # 3. Incremental assignment: try to assign to existing stories with centroids
    if has_embedding_provider:
        existing = db_stories.get_stories_with_centroid_in_window(since)
        assigned, to_cluster = _assign_to_existing_stories(to_cluster, existing, threshold)
        for article_id, story_id in assigned:
            db_stories.add_article_to_story(story_id, article_id)
            articles_in_story = db_stories.get_articles_in_story(story_id)
            distinct_before = len({a["source_id"] for a in articles_in_story[:-1]})
            distinct_after = len({a["source_id"] for a in articles_in_story})
            if distinct_after > distinct_before:
                db_stories.set_story_needs_rewrite(story_id, True)
            _update_story_centroid(story_id)
            report.stories_created += 0  # no new story, but article assigned

    # 4. Batch cluster remaining articles
    groups = _cluster_articles(to_cluster, threshold) if to_cluster else []

    # 5. Create story records only for groups with >= min_sources distinct sources
    for article_ids in groups:
        articles = db_articles.get_articles_by_ids(article_ids)
        distinct_sources = len({a["source_id"] for a in articles if a.get("source_id")})
        if distinct_sources < min_sources:
            continue
        story_id = db_stories.insert_story(article_ids)
        _update_story_centroid(story_id)
        report.stories_created += 1

    return report
