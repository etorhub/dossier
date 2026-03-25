"""Assign articles to stories by embedding similarity. Global grouping, same for all users."""

import logging
import os
import shutil
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from app.clustering.vectors import (
    compute_centroid as _compute_centroid,
    cosine_similarity as _cosine_similarity,
    embedding_from_article as _embedding_from_article,
    recompute_story_centroid as _update_story_centroid,
)
from app.config import load_config
from app.db import articles as db_articles
from app.db import stories as db_stories
from app.llm.embeddings import EmbeddingProviderError, get_embedding_provider
from app.llm.http_utils import is_ollama_connection_failure, quiet_http_library_info_logs

logger = logging.getLogger(__name__)


def _render_embedding_progress(
    done: int,
    total: int,
    title: str,
    *,
    frame: int,
) -> None:
    """One-line stderr progress (TTY only). Supplements quiet httpx logging."""
    if total <= 0 or not sys.stderr.isatty():
        return
    spin = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
    ch = spin[frame % len(spin)]
    pct = min(100, int(round(100.0 * done / total))) if total else 0
    bar_w = min(28, max(12, shutil.get_terminal_size((88, 24)).columns - 46))
    filled = min(bar_w, max(0, int(round(bar_w * done / total))))
    bar_f = "█" * filled + "░" * (bar_w - filled)
    safe = (title or "").replace("\n", " ").strip() or "—"
    if len(safe) > 40:
        safe = safe[:39] + "…"
    sys.stderr.write(
        f"\r\x1b[36m{ch}\x1b[0m embed \x1b[32m{bar_f}\x1b[0m "
        f"\x1b[1m{done}\x1b[0m/\x1b[1m{total}\x1b[0m {pct}%  "
        f"\x1b[2m{safe}\x1b[0m\x1b[K"
    )
    sys.stderr.flush()


@dataclass
class StoryReport:
    """Summary of a story assignment run."""

    articles_embedded: int
    articles_clustered: int
    stories_created: int


@dataclass(frozen=True)
class ExclusionRules:
    """Constraints from clustering_exclusion_rules (article pairs, source-pair thresholds)."""

    article_pairs: frozenset[frozenset[str]]
    source_pair_thresholds: dict[tuple[str, str], float]


def _load_exclusion_rules() -> ExclusionRules:
    """Load active exclusion rules from the database (ops / feedback agent)."""
    from app.db import admin as admin_db

    rows = admin_db.get_active_exclusion_rules()
    pairs: set[frozenset[str]] = set()
    source_thresholds: dict[tuple[str, str], float] = {}
    for r in rows:
        rt = r.get("rule_type")
        rd = r.get("rule_data")
        if not isinstance(rd, dict):
            continue
        if rt == "article_pair":
            a, b = rd.get("article_id_a"), rd.get("article_id_b")
            if isinstance(a, str) and isinstance(b, str) and a and b:
                pairs.add(frozenset((a, b)))
        elif rt == "source_pair":
            sa, sb = rd.get("source_a"), rd.get("source_b")
            if isinstance(sa, str) and isinstance(sb, str) and sa and sb:
                k = tuple(sorted((sa.strip(), sb.strip())))
                try:
                    ms = float(rd.get("min_similarity", 0.93))
                except (TypeError, ValueError):
                    ms = 0.93
                source_thresholds[k] = max(source_thresholds.get(k, 0.0), ms)
        # keyword: reserved for future heuristics
    return ExclusionRules(
        article_pairs=frozenset(pairs),
        source_pair_thresholds=source_thresholds,
    )


def _build_source_topics_index() -> dict[str, frozenset[str]]:
    """Return mapping source_id -> frozenset of topics, loaded from sources.yaml.

    Loaded once per cluster run. Used for the domain-compatibility gate.
    A source not found in the index is treated as general-capable (permissive default).
    """
    from app.config import load_sources

    index: dict[str, frozenset[str]] = {}
    for src in load_sources():
        sid = src.get("id")
        topics = src.get("topics") or []
        if sid and isinstance(topics, list):
            index[sid] = frozenset(str(t) for t in topics)
    return index


def _topics_compatible(
    source_id_a: str,
    source_id_b: str,
    source_topics: dict[str, frozenset[str]],
) -> bool:
    """Return False only if both sources are domain-exclusive with disjoint topic sets.

    A source is "domain-exclusive" if its topic set does not include "general".
    General-capable sources can always cluster with any other source.
    """
    topics_a = source_topics.get(source_id_a)
    topics_b = source_topics.get(source_id_b)
    if topics_a is None or topics_b is None:
        return True  # unknown source: permissive default
    if "general" in topics_a or "general" in topics_b:
        return True  # at least one general-capable source: always allow
    return bool(topics_a & topics_b)  # both exclusive: require non-empty intersection


def _effective_pair_threshold(
    art_a: dict[str, Any],
    art_b: dict[str, Any],
    global_threshold: float,
    rules: ExclusionRules,
) -> float:
    """Minimum cosine similarity required for this article pair to merge."""
    t = global_threshold
    sa = (art_a.get("source_id") or "").strip()
    sb = (art_b.get("source_id") or "").strip()
    if sa and sb and rules.source_pair_thresholds:
        key = tuple(sorted((sa, sb)))
        override = rules.source_pair_thresholds.get(key)
        if override is not None:
            t = max(t, override)
    return t


def _article_pair_blocked(rules: ExclusionRules, id_a: str, id_b: str) -> bool:
    return frozenset((id_a, id_b)) in rules.article_pairs


def _text_to_embed(article: dict[str, Any]) -> str:
    """Build text for embedding: domain prefix + title + content excerpt.

    The caller may inject '_source_topics' (list[str]) as a synthetic key on the
    article dict before calling. This key is never persisted to the database.
    """
    title = (article.get("title") or "").strip()
    full = (article.get("full_text") or "").strip()
    raw = (article.get("raw_text") or "").strip()
    content = (full or raw)[:2000]

    src_topics: list[str] = article.get("_source_topics") or []
    rss_cats: list[str] = [
        str(c).strip()
        for c in (article.get("categories") or [])
        if c and str(c).strip()
    ][:5]

    parts: list[str] = []
    if src_topics:
        parts.append("topics: " + ", ".join(sorted(src_topics)))
    if rss_cats:
        parts.append("categories: " + ", ".join(rss_cats))
    prefix = ". ".join(parts) + ". " if parts else ""

    return (prefix + title + " " + content).strip()


def _assign_to_existing_stories(
    articles: list[dict[str, Any]],
    existing_stories: list[dict[str, Any]],
    threshold: float,
    story_member_ids: dict[str, list[str]],
    rules: ExclusionRules,
    source_topics: dict[str, frozenset[str]],
    story_source_ids: dict[str, set[str]],
) -> tuple[list[tuple[str, str]], list[dict[str, Any]]]:
    """Try to assign articles to existing stories by centroid similarity.

    Returns (assigned list of (article_id, story_id), remaining articles).
    """
    assigned: list[tuple[str, str]] = []
    remaining: list[dict[str, Any]] = []
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
            if rules.article_pairs:
                blocked = False
                for mid in story_member_ids.get(sid, []):
                    if _article_pair_blocked(rules, art["id"], mid):
                        blocked = True
                        break
                if blocked:
                    continue
            art_src = (art.get("source_id") or "").strip()
            if art_src:
                story_srcs = story_source_ids.get(sid, set())
                if story_srcs and not all(
                    _topics_compatible(art_src, src_id, source_topics) for src_id in story_srcs
                ):
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


def _cluster_articles(
    articles: list[dict[str, Any]],
    threshold: float,
    rules: ExclusionRules,
    source_topics: dict[str, frozenset[str]],
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
                cross_ok = True
                min_sim = 1.0
                for a in g1:
                    for b in g2:
                        key = (a, b) if a < b else (b, a)
                        raw = sim.get(key, 0.0)
                        art_a, art_b = articles[a], articles[b]
                        if rules.article_pairs and _article_pair_blocked(
                            rules, art_a["id"], art_b["id"]
                        ):
                            cross_ok = False
                            break
                        sa = art_a.get("source_id") or ""
                        sb = art_b.get("source_id") or ""
                        if sa and sb and not _topics_compatible(sa, sb, source_topics):
                            cross_ok = False
                            break
                        tneed = _effective_pair_threshold(art_a, art_b, threshold, rules)
                        if raw < tneed:
                            cross_ok = False
                            break
                        min_sim = min(min_sim, raw)
                    if not cross_ok:
                        break
                if cross_ok and min_sim >= threshold and min_sim > best_min_sim:
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
    exclusion_rules = _load_exclusion_rules()
    source_topics = _build_source_topics_index()

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
        eligible: list[tuple[int, dict[str, Any], str]] = []
        for i, article in enumerate(to_embed):
            article["_source_topics"] = list(source_topics.get(article.get("source_id") or "", frozenset()))
            text = _text_to_embed(article)
            if text:
                eligible.append((i, article, text))
        total_eligible = len(eligible)
        with quiet_http_library_info_logs():
            try:
                for k, (i, article, text) in enumerate(eligible):
                    try:
                        embedding = provider.embed(text)
                        db_articles.update_article_embedding(article["id"], embedding)
                        report.articles_embedded += 1
                        title = str(article.get("title") or article.get("id") or "")
                        _render_embedding_progress(
                            report.articles_embedded,
                            total_eligible,
                            title,
                            frame=k,
                        )
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
            finally:
                if sys.stderr.isatty() and total_eligible > 0:
                    sys.stderr.write("\n")
                    sys.stderr.flush()

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
        story_member_ids: dict[str, list[str]] = {}
        story_source_ids: dict[str, set[str]] = {}
        for row in existing:
            sid = row["story_id"]
            members = db_stories.get_articles_in_story(sid)
            story_member_ids[sid] = [a["id"] for a in members]
            story_source_ids[sid] = {a["source_id"] for a in members if a.get("source_id")}
        assigned, to_cluster = _assign_to_existing_stories(
            to_cluster, existing, threshold, story_member_ids, exclusion_rules,
            source_topics, story_source_ids,
        )
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
    groups = _cluster_articles(to_cluster, threshold, exclusion_rules, source_topics) if to_cluster else []

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
