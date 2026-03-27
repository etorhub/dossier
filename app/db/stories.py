"""CRUD operations for stories, story_articles, story_rewrites."""

import json
import logging
import uuid
from datetime import datetime
from typing import Any, cast

import psycopg2.extras
from psycopg2.errors import UniqueViolation

from app.db.connection import get_connection, return_connection

logger = logging.getLogger(__name__)


def insert_story(article_ids: list[str]) -> str:
    """Create a story with the given articles. Returns story_id (UUID string).

    Idempotent: if the same article set already forms a story, returns that story_id.
    """
    if not article_ids:
        raise ValueError("Cannot create story with no articles")
    wanted = set(article_ids)
    existing_map = get_story_ids_for_articles(article_ids)
    if existing_map:
        if set(existing_map.keys()) != wanted:
            raise ValueError("insert_story: article group mixes assigned and unassigned articles")
        story_ids_set = set(existing_map.values())
        if len(story_ids_set) != 1:
            raise ValueError(
                f"insert_story: articles belong to different stories: {story_ids_set!r}"
            )
        sid = next(iter(story_ids_set))
        members = {a["id"] for a in get_articles_in_story(sid)}
        if members == wanted:
            return sid
        raise ValueError("insert_story: story membership does not match article group")

    story_id = str(uuid.uuid4())
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO stories (id) VALUES (%s::uuid)",
                (story_id,),
            )
            for pos, aid in enumerate(article_ids):
                cur.execute(
                    """
                    INSERT INTO story_articles (story_id, article_id, position)
                    VALUES (%s::uuid, %s, %s)
                    """,
                    (story_id, aid, pos),
                )
        conn.commit()
        return story_id
    except UniqueViolation:
        conn.rollback()
        again = get_story_ids_for_articles(article_ids)
        if (
            set(again.keys()) == wanted
            and len(set(again.values())) == 1
            and {a["id"] for a in get_articles_in_story(next(iter(set(again.values()))))} == wanted
        ):
            return next(iter(set(again.values())))
        logger.warning(
            "insert_story: unique violation on story_articles; could not resolve idempotently"
        )
        raise
    finally:
        return_connection(conn)


def add_article_to_story(story_id: str, article_id: str) -> None:
    """Append an article to an existing story. No-op if already linked to this story."""
    existing = get_story_ids_for_articles([article_id])
    sid = existing.get(article_id)
    if sid is not None:
        if sid == story_id:
            return
        logger.warning(
            "add_article_to_story: article %s already in story %s; skip add to %s",
            article_id,
            sid,
            story_id,
        )
        return
    conn = get_connection()
    try:
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT COALESCE(MAX(position), -1) + 1 AS next_pos
                    FROM story_articles WHERE story_id = %s::uuid
                    """,
                    (story_id,),
                )
                row = cur.fetchone()
                pos = row[0] if row else 0
                cur.execute(
                    """
                    INSERT INTO story_articles (story_id, article_id, position)
                    VALUES (%s::uuid, %s, %s)
                    """,
                    (story_id, article_id, pos),
                )
            conn.commit()
        except UniqueViolation:
            conn.rollback()
    finally:
        return_connection(conn)


def dissolve_story(story_id: str, reason: str) -> None:
    """Dissolve an incoherent story: delete its article memberships and mark it coherence_failed.

    The story row is kept for audit. Articles freed here will be eligible for re-clustering
    on the next clustering run if they are still within cluster_window_hours.
    """
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM story_articles WHERE story_id = %s::uuid",
                (story_id,),
            )
            cur.execute(
                """
                UPDATE stories
                SET coherence_failed = TRUE,
                    coherence_reason = %s
                WHERE id = %s::uuid
                """,
                (reason[:500], story_id),
            )
        conn.commit()
        logger.info("dissolve_story: story_id=%s reason=%s", story_id, reason[:120])
    finally:
        return_connection(conn)


def remove_article_from_story(story_id: str, article_id: str) -> bool:
    """Remove an article from a story. Returns True if a membership row was deleted."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                DELETE FROM story_articles
                WHERE story_id = %s::uuid AND article_id = %s
                """,
                (story_id, article_id),
            )
            deleted = bool(cur.rowcount > 0)
        conn.commit()
        return deleted
    finally:
        return_connection(conn)


def get_articles_in_story(story_id: str) -> list[dict[str, Any]]:
    """Return articles in a story, ordered by position."""
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT a.*, sa.position
                FROM articles a
                JOIN story_articles sa ON sa.article_id = a.id
                WHERE sa.story_id = %s::uuid
                ORDER BY sa.position
                """,
                (story_id,),
            )
            rows = cur.fetchall()
            return [dict(row) for row in rows]
    finally:
        return_connection(conn)


def get_story_ids_for_articles(article_ids: list[str]) -> dict[str, str]:
    """Return mapping article_id -> story_id for articles that are in a story."""
    if not article_ids:
        return {}
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT article_id, story_id::text
                FROM story_articles
                WHERE article_id = ANY(%s)
                """,
                (article_ids,),
            )
            return {row["article_id"]: row["story_id"] for row in cur.fetchall()}
    finally:
        return_connection(conn)


def get_stories_with_articles_in_window(
    since: datetime | None,
    source_ids: set[str] | None = None,
    topic_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Return stories that have at least one article.

    If since is not None, only stories with articles published since that time.
    If since is None, return all stories (ordered by most recent article).
    Source/topic filtering is done at the service layer.
    """
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            if since is not None:
                cur.execute(
                    """
                    SELECT DISTINCT s.id::text as story_id, s.created_at
                    FROM stories s
                    JOIN story_articles sa ON sa.story_id = s.id
                    JOIN articles a ON a.id = sa.article_id
                    WHERE a.published_at >= %s
                      AND (s.coherence_failed = FALSE OR s.coherence_failed IS NULL)
                    ORDER BY s.created_at DESC
                    """,
                    (since,),
                )
            else:
                cur.execute(
                    """
                    SELECT DISTINCT s.id::text as story_id, s.created_at
                    FROM stories s
                    JOIN story_articles sa ON sa.story_id = s.id
                    JOIN articles a ON a.id = sa.article_id
                    WHERE (s.coherence_failed = FALSE OR s.coherence_failed IS NULL)
                    ORDER BY s.created_at DESC
                    """
                )
            return [dict(row) for row in cur.fetchall()]
    finally:
        return_connection(conn)


def get_stories_needing_rewrite_for_variant(
    style: str,
    language: str,
    since: datetime | None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Return stories that have no rewrite for this (style, language) variant.

    If since is not None, only stories with articles published since that time.
    If since is None, return all stories needing this variant.
    """
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            if since is not None:
                cur.execute(
                    """
                    SELECT s.id::text as story_id
                    FROM stories s
                    JOIN story_articles sa ON sa.story_id = s.id
                    JOIN articles a ON a.id = sa.article_id
                    LEFT JOIN story_rewrites sr ON sr.story_id = s.id
                        AND sr.style = %s AND sr.language = %s
                    WHERE a.published_at >= %s AND sr.story_id IS NULL
                    GROUP BY s.id
                    ORDER BY MAX(a.published_at) DESC
                    """,
                    (style, language, since),
                )
            else:
                cur.execute(
                    """
                    SELECT s.id::text as story_id
                    FROM stories s
                    JOIN story_articles sa ON sa.story_id = s.id
                    JOIN articles a ON a.id = sa.article_id
                    LEFT JOIN story_rewrites sr ON sr.story_id = s.id
                        AND sr.style = %s AND sr.language = %s
                    WHERE sr.story_id IS NULL
                    GROUP BY s.id
                    ORDER BY MAX(a.published_at) DESC
                    """,
                    (style, language),
                )
            rows = cur.fetchall()
            if limit is not None:
                rows = rows[:limit]
            return [dict(row) for row in rows]
    finally:
        return_connection(conn)


def insert_story_rewrite(
    story_id: str,
    style: str,
    language: str,
    title: str | None,
    summary: str | None,
    full_text: str | None,
    rewrite_failed: bool = False,
    error_message: str | None = None,
) -> None:
    """Insert or update a story rewrite for (story_id, style, language)."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO story_rewrites (
                    story_id, style, language, title, summary, full_text,
                    rewrite_failed, error_message
                )
                VALUES (%s::uuid, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (story_id, style, language)
                DO UPDATE SET
                    title = EXCLUDED.title,
                    summary = EXCLUDED.summary,
                    full_text = EXCLUDED.full_text,
                    rewrite_failed = EXCLUDED.rewrite_failed,
                    error_message = EXCLUDED.error_message
                """,
                (
                    story_id,
                    style,
                    language,
                    title,
                    summary,
                    full_text,
                    rewrite_failed,
                    error_message,
                ),
            )
        conn.commit()
    finally:
        return_connection(conn)


def get_story_rewrites(
    story_ids: list[str],
    style: str,
    language: str,
) -> dict[str, dict[str, Any]]:
    """Return rewrites for story_ids and (style, language), keyed by story_id."""
    if not story_ids:
        return {}
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT story_id::text, title, summary, full_text,
                       highlighted_full_text, rewrite_failed
                FROM story_rewrites
                WHERE style = %s AND language = %s AND story_id::text = ANY(%s)
                """,
                (style, language, story_ids),
            )
            return {row["story_id"]: dict(row) for row in cur.fetchall()}
    finally:
        return_connection(conn)


def update_story_rewrite_highlight(
    story_id: str,
    style: str,
    language: str,
    highlighted_full_text: str,
) -> None:
    """Store the highlighted version of full_text for (story_id, style, language)."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE story_rewrites
                SET highlighted_full_text = %s
                WHERE story_id = %s::uuid AND style = %s AND language = %s
                """,
                (highlighted_full_text, story_id, style, language),
            )
        conn.commit()
    finally:
        return_connection(conn)


def get_stories_needing_highlight(
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Return story_rewrites rows with full_text but no highlighted_full_text yet."""
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT sr.story_id::text, sr.style, sr.language, sr.full_text
                FROM story_rewrites sr
                JOIN stories s ON s.id = sr.story_id
                WHERE sr.full_text IS NOT NULL
                  AND (sr.rewrite_failed = false OR sr.rewrite_failed IS NULL)
                  AND sr.highlighted_full_text IS NULL
                  AND (s.coherence_failed = FALSE OR s.coherence_failed IS NULL)
                ORDER BY sr.story_id
                """
                + (" LIMIT %s" if limit is not None else ""),
                (limit,) if limit is not None else (),
            )
            return [dict(row) for row in cur.fetchall()]
    finally:
        return_connection(conn)


def story_exists(story_id: str) -> bool:
    """Return True if story exists."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM stories WHERE id = %s::uuid", (story_id,))
            return cur.fetchone() is not None
    finally:
        return_connection(conn)


def get_story_centroid(story_id: str) -> list[float] | None:
    """Return cached centroid embedding for story, or None."""
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT centroid_embedding FROM stories WHERE id = %s::uuid",
                (story_id,),
            )
            row = cur.fetchone()
            if not row or not row.get("centroid_embedding"):
                return None
            emb = row["centroid_embedding"]
            if isinstance(emb, list):
                return emb
            if isinstance(emb, str):
                return cast(list[float], json.loads(emb))
            return None
    finally:
        return_connection(conn)


def update_story_centroid(story_id: str, embedding: list[float]) -> None:
    """Store centroid embedding for story. Writes to JSONB and pgvector columns."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            vec_str = "[" + ",".join(str(x) for x in embedding) + "]"
            cur.execute(
                """UPDATE stories
                   SET centroid_embedding = %s::jsonb,
                       centroid_vec = %s::vector
                   WHERE id = %s::uuid""",
                (json.dumps(embedding), vec_str, story_id),
            )
        conn.commit()
    finally:
        return_connection(conn)


def clear_story_centroid(story_id: str) -> None:
    """Set story centroid to NULL (e.g. after all articles were removed)."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE stories SET centroid_embedding = NULL WHERE id = %s::uuid",
                (story_id,),
            )
        conn.commit()
    finally:
        return_connection(conn)


def set_story_needs_rewrite(story_id: str, needs: bool = True) -> None:
    """Mark story as needing rewrite (or clear the flag)."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE stories SET needs_rewrite = %s WHERE id = %s::uuid",
                (needs, story_id),
            )
        conn.commit()
    finally:
        return_connection(conn)


def set_story_last_rewrite_at(story_id: str) -> None:
    """Record that a successful cascade rewrite completed for this story."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE stories SET last_rewrite_at = NOW() WHERE id = %s::uuid",
                (story_id,),
            )
        conn.commit()
    finally:
        return_connection(conn)


def get_stories_with_centroid_in_window(since: datetime | None) -> list[dict[str, Any]]:
    """Return stories with centroid_embedding for incremental assignment.

    If since is not None, only stories that have an article with published_at >= since.
    If since is None, all stories with a centroid.
    """
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            if since is not None:
                cur.execute(
                    """
                    SELECT s.id::text as story_id, s.centroid_embedding
                    FROM stories s
                    JOIN story_articles sa ON sa.story_id = s.id
                    JOIN articles a ON a.id = sa.article_id
                    WHERE a.published_at >= %s AND s.centroid_embedding IS NOT NULL
                    GROUP BY s.id
                    """,
                    (since,),
                )
            else:
                cur.execute(
                    """
                    SELECT s.id::text as story_id, s.centroid_embedding
                    FROM stories s
                    JOIN story_articles sa ON sa.story_id = s.id
                    JOIN articles a ON a.id = sa.article_id
                    WHERE s.centroid_embedding IS NOT NULL
                    GROUP BY s.id
                    """
                )
            rows = cur.fetchall()
            result: list[dict[str, Any]] = []
            for row in rows:
                d = dict(row)
                emb = d.get("centroid_embedding")
                if isinstance(emb, str):
                    try:
                        d["centroid_embedding"] = json.loads(emb)
                    except json.JSONDecodeError:
                        d["centroid_embedding"] = None
                result.append(d)
            return result
    finally:
        return_connection(conn)


def get_top_k_story_candidates(
    embedding: list[float],
    k: int,
    since: datetime | None,
) -> list[dict[str, Any]]:
    """Return top-k stories nearest to embedding using pgvector ANN (cosine distance).

    Requires migration 029 (pgvector extension + centroid_vec column).
    Results are ordered by similarity DESC. Suitable for use with
    processing.cluster_use_ivfflat = true.
    """
    if not embedding:
        return []
    vec_str = "[" + ",".join(str(x) for x in embedding) + "]"
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            if since is not None:
                cur.execute(
                    """
                    SELECT s.id::text AS story_id,
                           1 - (s.centroid_vec <=> %s::vector) AS sim
                    FROM stories s
                    WHERE s.centroid_vec IS NOT NULL
                      AND EXISTS (
                          SELECT 1 FROM story_articles sa
                          JOIN articles a ON a.id = sa.article_id
                          WHERE sa.story_id = s.id AND a.published_at >= %s
                      )
                    ORDER BY s.centroid_vec <=> %s::vector
                    LIMIT %s
                    """,
                    (vec_str, since, vec_str, k),
                )
            else:
                cur.execute(
                    """
                    SELECT s.id::text AS story_id,
                           1 - (s.centroid_vec <=> %s::vector) AS sim
                    FROM stories s
                    WHERE s.centroid_vec IS NOT NULL
                    ORDER BY s.centroid_vec <=> %s::vector
                    LIMIT %s
                    """,
                    (vec_str, vec_str, k),
                )
            return [dict(row) for row in cur.fetchall()]
    finally:
        return_connection(conn)


def get_all_rewrites_for_story(story_id: str) -> dict[tuple[str, str], dict[str, Any]]:
    """Return all existing non-failed rewrites for a story, keyed by (style, language)."""
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT style, language, title, summary, full_text
                FROM story_rewrites
                WHERE story_id = %s::uuid AND (rewrite_failed = false OR rewrite_failed IS NULL)
                """,
                (story_id,),
            )
            result: dict[tuple[str, str], dict[str, Any]] = {}
            for row in cur.fetchall():
                key = (row["style"], row["language"])
                result[key] = dict(row)
            return result
    finally:
        return_connection(conn)


def get_articles_for_stories(story_ids: list[str]) -> dict[str, list[dict[str, Any]]]:
    """Return articles for multiple stories in a single query.

    Returns a dict mapping story_id (str) -> list of article dicts ordered by position.
    Stories with no articles are not included in the result.
    """
    if not story_ids:
        return {}
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT a.*, sa.story_id::text AS _story_id, sa.position
                FROM articles a
                JOIN story_articles sa ON sa.article_id = a.id
                WHERE sa.story_id = ANY(%s::uuid[])
                ORDER BY sa.story_id, sa.position
                """,
                (story_ids,),
            )
            result: dict[str, list[dict[str, Any]]] = {}
            for row in cur.fetchall():
                d = dict(row)
                sid = d.pop("_story_id")
                result.setdefault(sid, []).append(d)
        return result
    finally:
        return_connection(conn)


def get_all_rewrites_for_stories(
    story_ids: list[str],
) -> dict[str, dict[tuple[str, str], dict[str, Any]]]:
    """Return all non-failed rewrites for multiple stories in a single query.

    Returns a dict mapping story_id (str) -> {(style, language): rewrite_dict}.
    Same structure as get_all_rewrites_for_story but for a batch.
    Stories with no rewrites are not included in the result.
    """
    if not story_ids:
        return {}
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT story_id::text AS story_id, style, language, title, summary, full_text
                FROM story_rewrites
                WHERE story_id = ANY(%s::uuid[])
                  AND (rewrite_failed = false OR rewrite_failed IS NULL)
                """,
                (story_ids,),
            )
            result: dict[str, dict[tuple[str, str], dict[str, Any]]] = {}
            for row in cur.fetchall():
                d = dict(row)
                sid = d["story_id"]
                key: tuple[str, str] = (d["style"], d["language"])
                result.setdefault(sid, {})[key] = d
        return result
    finally:
        return_connection(conn)


def get_all_stories_with_articles(
    since: datetime | None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Return every story that has at least one linked article.

    Ordered by newest linked article ``published_at`` descending. Optional
    ``since`` restricts to stories with at least one article on or after that
    time (same window semantics as the scheduled rewrite job). Used for
    operator-driven full rewrites when prompts or models change.
    """
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            if since is not None:
                cur.execute(
                    """
                    SELECT s.id::text AS story_id, MAX(a.published_at) AS max_pub
                    FROM stories s
                    JOIN story_articles sa ON sa.story_id = s.id
                    JOIN articles a ON a.id = sa.article_id
                    WHERE a.published_at >= %s
                    GROUP BY s.id
                    ORDER BY max_pub DESC
                    """
                    + (" LIMIT %s" if limit is not None and limit > 0 else ""),
                    (since,) + ((limit,) if limit is not None and limit > 0 else ()),
                )
            else:
                cur.execute(
                    """
                    SELECT s.id::text AS story_id, MAX(a.published_at) AS max_pub
                    FROM stories s
                    JOIN story_articles sa ON sa.story_id = s.id
                    JOIN articles a ON a.id = sa.article_id
                    GROUP BY s.id
                    ORDER BY max_pub DESC
                    """
                    + (" LIMIT %s" if limit is not None and limit > 0 else ""),
                    (limit,) if limit is not None and limit > 0 else (),
                )
            rows = cur.fetchall()
            return [dict(row) for row in rows]
    finally:
        return_connection(conn)


def get_stories_needing_any_rewrite(
    variants: list[tuple[str, str]],
    since: datetime | None,
    limit: int | None = None,
    cooldown_minutes: int = 0,
) -> list[dict[str, Any]]:
    """Return stories missing at least one variant, or with needs_rewrite=true.

    variants: list of (style, language) tuples that must exist.
    If since is not None, prefer stories with articles published since that time;
    stories with needs_rewrite=true are always included so ops edits (e.g. removing
    an article) still get a full cascade rewrite on the next batch.
    cooldown_minutes: if > 0, stories with needs_rewrite=true that were rewritten
    within this window are deferred (first-time rewrites always proceed).
    """
    if not variants:
        return []
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            # Build VALUES clause for required variants
            values_placeholders = ", ".join("(%s, %s)" for _ in variants)
            flat_variants = [item for pair in variants for item in pair]
            required_count = len(variants)

            # Cooldown: defer recently-rewritten stories (needs_rewrite=true only)
            cooldown_filter = ""
            cooldown_params: list[Any] = []
            if cooldown_minutes > 0:
                cooldown_filter = (
                    "\nAND NOT (\n"
                    "  sc.needs_rewrite = TRUE\n"
                    "  AND sc.last_rewrite_at IS NOT NULL\n"
                    "  AND sc.last_rewrite_at > NOW() - %s::interval\n"
                    ")"
                )
                cooldown_params = [f"{cooldown_minutes} minutes"]

            if since is not None:
                cur.execute(
                    f"""
                    WITH required AS (
                        SELECT * FROM (VALUES {values_placeholders}) AS t(style, lang)
                    ),
                    story_counts AS (
                        SELECT s.id, s.needs_rewrite, s.last_rewrite_at,
                            MAX(a.published_at) AS max_pub,
                            (SELECT count(*) FROM story_rewrites sr
                             WHERE sr.story_id = s.id
                               AND (sr.rewrite_failed = false OR sr.rewrite_failed IS NULL)
                               AND (sr.style, sr.language) IN (SELECT style, lang FROM required)
                            ) AS have_count
                        FROM stories s
                        JOIN story_articles sa ON sa.story_id = s.id
                        JOIN articles a ON a.id = sa.article_id
                        WHERE (a.published_at >= %s OR s.needs_rewrite = true)
                        GROUP BY s.id
                    )
                    SELECT sc.id::text AS story_id, sc.needs_rewrite
                    FROM story_counts sc
                    WHERE (sc.needs_rewrite = true OR sc.have_count < %s)
                    {cooldown_filter}
                    ORDER BY sc.max_pub DESC
                    """
                    + (" LIMIT %s" if limit is not None and limit > 0 else ""),
                    flat_variants
                    + [since, required_count]
                    + cooldown_params
                    + ([limit] if limit is not None and limit > 0 else []),
                )
            else:
                cur.execute(
                    f"""
                    WITH required AS (
                        SELECT * FROM (VALUES {values_placeholders}) AS t(style, lang)
                    ),
                    story_counts AS (
                        SELECT s.id, s.needs_rewrite, s.last_rewrite_at,
                            MAX(a.published_at) AS max_pub,
                            (SELECT count(*) FROM story_rewrites sr
                             WHERE sr.story_id = s.id
                               AND (sr.rewrite_failed = false OR sr.rewrite_failed IS NULL)
                               AND (sr.style, sr.language) IN (SELECT style, lang FROM required)
                            ) AS have_count
                        FROM stories s
                        JOIN story_articles sa ON sa.story_id = s.id
                        JOIN articles a ON a.id = sa.article_id
                        GROUP BY s.id
                    )
                    SELECT sc.id::text AS story_id, sc.needs_rewrite
                    FROM story_counts sc
                    WHERE (sc.needs_rewrite = true OR sc.have_count < %s)
                    {cooldown_filter}
                    ORDER BY sc.max_pub DESC
                    """
                    + (" LIMIT %s" if limit is not None and limit > 0 else ""),
                    flat_variants
                    + [required_count]
                    + cooldown_params
                    + ([limit] if limit is not None and limit > 0 else []),
                )
            rows = cur.fetchall()
            return [dict(row) for row in rows]
    finally:
        return_connection(conn)


def get_stories_needing_rewrite(
    style: str, language: str, since: datetime | None
) -> list[dict[str, Any]]:
    """Return stories that need rewrite: either no rewrite or needs_rewrite=True."""
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            if since is not None:
                cur.execute(
                    """
                    SELECT s.id::text as story_id
                    FROM stories s
                    JOIN story_articles sa ON sa.story_id = s.id
                    JOIN articles a ON a.id = sa.article_id
                    LEFT JOIN story_rewrites sr ON sr.story_id = s.id
                        AND sr.style = %s AND sr.language = %s
                    WHERE (a.published_at >= %s OR s.needs_rewrite = true)
                      AND (sr.story_id IS NULL OR s.needs_rewrite = true)
                    GROUP BY s.id
                    ORDER BY MAX(a.published_at) DESC
                    """,
                    (style, language, since),
                )
            else:
                cur.execute(
                    """
                    SELECT s.id::text as story_id
                    FROM stories s
                    JOIN story_articles sa ON sa.story_id = s.id
                    JOIN articles a ON a.id = sa.article_id
                    LEFT JOIN story_rewrites sr ON sr.story_id = s.id
                        AND sr.style = %s AND sr.language = %s
                    WHERE sr.story_id IS NULL OR s.needs_rewrite = true
                    GROUP BY s.id
                    ORDER BY MAX(a.published_at) DESC
                    """,
                    (style, language),
                )
            return [dict(row) for row in cur.fetchall()]
    finally:
        return_connection(conn)
