"""CRUD operations for the articles table."""

import hashlib
import json
from datetime import datetime
from typing import Any

import psycopg2.extras

from app.db.connection import get_connection, return_connection


def _sql_article_has_valid_embedding(column: str = "embedding") -> str:
    """SQL fragment: true when column holds a non-empty JSON array (embedding vector)."""
    return (
        f"({column} IS NOT NULL AND jsonb_typeof({column}) = 'array' "
        f"AND jsonb_array_length({column}) > 0)"
    )


def _article_id(source_id: str, url: str) -> str:
    """Generate deterministic article id from source_id and url."""
    return hashlib.sha256(f"{source_id}:{url}".encode()).hexdigest()[:16]


def get_article_by_id(article_id: str) -> dict[str, Any] | None:
    """Return article dict or None if not found."""
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT * FROM articles WHERE id = %s", (article_id,))
            row = cur.fetchone()
            return dict(row) if row else None
    finally:
        return_connection(conn)


def insert_article(article: dict[str, Any]) -> bool:
    """Insert an article. Returns True if inserted, False if duplicate.

    Article dict must have: title, url, source_id. Optional: published_at,
    raw_text, full_text, guid, image_url, image_source, categories,
    article_type ('news' or 'non_news', defaults to 'news'). Id is generated
    from source_id:url.
    """
    article_id = _article_id(article["source_id"], article["url"])
    categories = article.get("categories")
    if categories is None:
        categories = []
    if not isinstance(categories, list):
        categories = []
    categories_json = json.dumps(categories)
    article_type = article.get("article_type") or "news"

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO articles (
                    id, title, url, source_id, published_at,
                    raw_text, full_text, guid, image_url, image_source,
                    categories, article_type
                )
                VALUES (
                    %(id)s, %(title)s, %(url)s, %(source_id)s, %(published_at)s,
                    %(raw_text)s, %(full_text)s, %(guid)s, %(image_url)s,
                    %(image_source)s, %(categories)s::jsonb, %(article_type)s
                )
                ON CONFLICT (source_id, url) DO NOTHING
                """,
                {
                    "id": article_id,
                    "title": article["title"],
                    "url": article["url"],
                    "source_id": article["source_id"],
                    "published_at": article.get("published_at"),
                    "raw_text": article.get("raw_text"),
                    "full_text": article.get("full_text"),
                    "guid": article.get("guid"),
                    "image_url": article.get("image_url"),
                    "image_source": article.get("image_source"),
                    "categories": categories_json,
                    "article_type": article_type,
                },
            )
            inserted = bool(cur.rowcount > 0)
        conn.commit()
        return inserted
    finally:
        return_connection(conn)


def article_exists(source_id: str, url: str) -> bool:
    """Return True if an article with this source_id and url exists."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM articles WHERE source_id = %s AND url = %s",
                (source_id, url),
            )
            return cur.fetchone() is not None
    finally:
        return_connection(conn)


def update_article_embedding(article_id: str, embedding: list[float]) -> None:
    """Store embedding for an article. Embedding is stored as JSONB."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE articles SET embedding = %s::jsonb WHERE id = %s",
                (json.dumps(embedding), article_id),
            )
        conn.commit()
    finally:
        return_connection(conn)


def get_recent_articles_without_embedding(
    since: datetime | None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Return news articles with no embedding yet.

    Non-news articles are excluded — they are never embedded or clustered.
    If since is not None, only articles with published_at >= since.
    If since is None, all articles without an embedding.
    """
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            need = f"NOT ({_sql_article_has_valid_embedding('embedding')})"
            if since is not None:
                cur.execute(
                    f"""
                    SELECT * FROM articles
                    WHERE published_at >= %s AND {need} AND article_type = 'news'
                    ORDER BY published_at DESC
                    """,
                    (since,),
                )
            else:
                cur.execute(
                    f"""
                    SELECT * FROM articles
                    WHERE {need} AND article_type = 'news'
                    ORDER BY published_at DESC NULLS LAST
                    """
                )
            rows = cur.fetchall()
            if limit is not None:
                rows = rows[:limit]
            return [dict(row) for row in rows]
    finally:
        return_connection(conn)


def count_recent_articles_without_embedding(since: datetime | None) -> int:
    """Count articles with no valid embedding (same filter as get_recent_articles_without_embedding)."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            need = f"NOT ({_sql_article_has_valid_embedding('embedding')})"
            if since is not None:
                cur.execute(
                    f"""
                    SELECT COUNT(*) FROM articles
                    WHERE published_at >= %s AND {need}
                    """,
                    (since,),
                )
            else:
                cur.execute(
                    f"""
                    SELECT COUNT(*) FROM articles
                    WHERE {need}
                    """
                )
            row = cur.fetchone()
            return int(row[0]) if row else 0
    finally:
        return_connection(conn)


def count_articles_published_since(since: datetime | None) -> int:
    """Count articles with published_at >= since. If since is None, count all articles."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            if since is not None:
                cur.execute(
                    "SELECT COUNT(*) FROM articles WHERE published_at >= %s",
                    (since,),
                )
            else:
                cur.execute("SELECT COUNT(*) FROM articles")
            row = cur.fetchone()
            return int(row[0]) if row else 0
    finally:
        return_connection(conn)


def count_recent_articles_with_valid_embedding(since: datetime | None) -> int:
    """Count articles with a valid embedding; if since is set, only published_at >= since."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            has_emb = _sql_article_has_valid_embedding("embedding")
            if since is not None:
                cur.execute(
                    f"""
                    SELECT COUNT(*) FROM articles
                    WHERE published_at >= %s AND {has_emb}
                    """,
                    (since,),
                )
            else:
                cur.execute(
                    f"""
                    SELECT COUNT(*) FROM articles
                    WHERE {has_emb}
                    """
                )
            row = cur.fetchone()
            return int(row[0]) if row else 0
    finally:
        return_connection(conn)


def get_recent_articles_with_embedding(
    since: datetime,
) -> list[dict[str, Any]]:
    """Return news articles since given time that have embeddings, for clustering."""
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            has_emb = _sql_article_has_valid_embedding("embedding")
            cur.execute(
                f"""
                SELECT * FROM articles
                WHERE published_at >= %s AND {has_emb} AND article_type = 'news'
                ORDER BY published_at DESC
                """,
                (since,),
            )
            return [dict(row) for row in cur.fetchall()]
    finally:
        return_connection(conn)


def get_articles_with_embedding_not_in_story(since: datetime | None) -> list[dict[str, Any]]:
    """Return articles with embeddings not yet in any story, optionally filtered by published_at."""
    return _get_articles_not_in_story(since, require_embedding=True)


def get_articles_not_in_story(since: datetime | None) -> list[dict[str, Any]]:
    """Return articles not in any story (with or without embedding), optionally by published_at."""
    return _get_articles_not_in_story(since, require_embedding=False)


def _get_articles_not_in_story(
    since: datetime | None,
    require_embedding: bool = True,
) -> list[dict[str, Any]]:
    """Return news articles not in a story. Optionally require embedding.

    Non-news articles are excluded — they are never clustered into stories.
    If since is not None, only articles with published_at >= since.
    """
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            time_clause = " AND a.published_at >= %s" if since is not None else ""
            params: tuple[Any, ...] = (since,) if since is not None else ()
            has_emb = _sql_article_has_valid_embedding("a.embedding")
            if require_embedding:
                cur.execute(
                    f"""
                    SELECT a.* FROM articles a
                    LEFT JOIN story_articles sa ON sa.article_id = a.id
                    WHERE {has_emb}
                      AND sa.article_id IS NULL
                      AND a.article_type = 'news'
                      {time_clause}
                    ORDER BY a.published_at DESC NULLS LAST
                    """,
                    params,
                )
            else:
                cur.execute(
                    f"""
                    SELECT a.* FROM articles a
                    LEFT JOIN story_articles sa ON sa.article_id = a.id
                    WHERE sa.article_id IS NULL
                      AND a.article_type = 'news'
                      {time_clause}
                    ORDER BY a.published_at DESC NULLS LAST
                    """,
                    params,
                )
            return [dict(row) for row in cur.fetchall()]
    finally:
        return_connection(conn)


def get_articles_by_ids(article_ids: list[str]) -> list[dict[str, Any]]:
    """Return articles by id list, preserving order where possible."""
    if not article_ids:
        return []
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT * FROM articles WHERE id = ANY(%s)",
                (article_ids,),
            )
            by_id = {row["id"]: dict(row) for row in cur.fetchall()}
            return [by_id[aid] for aid in article_ids if aid in by_id]
    finally:
        return_connection(conn)


def get_pending_extraction_count() -> int:
    """Return count of articles with extraction_status = 'pending'."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM articles WHERE extraction_status = 'pending'"
            )
            row = cur.fetchone()
            return int(row[0]) if row else 0
    finally:
        return_connection(conn)


def get_articles_needing_extraction(limit: int) -> list[dict[str, Any]]:
    """Return news articles with extraction_status = 'pending', by fetched_at DESC.

    Non-news articles are excluded — they are stored in the DB for operator
    review but never enriched.
    """
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, title, url, source_id, full_text, raw_text, image_url
                FROM articles
                WHERE extraction_status = 'pending'
                  AND article_type = 'news'
                ORDER BY fetched_at DESC NULLS LAST
                LIMIT %s
                """,
                (limit,),
            )
            return [dict(row) for row in cur.fetchall()]
    finally:
        return_connection(conn)


def update_article_extraction(
    article_id: str,
    full_text: str | None,
    status: str,
    method: str,
    image_url: str | None = None,
    image_source: str | None = None,
    *,
    replace_image: bool = False,
) -> None:
    """Update article with extraction result.

    If image_url and image_source are provided, they are written when ``replace_image``
    is true, or merged with ``COALESCE`` so an existing image is kept when
    ``replace_image`` is false (e.g. first-time og:image fallback).
    """
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            if image_url is not None and image_source is not None:
                if replace_image:
                    cur.execute(
                        """
                        UPDATE articles
                        SET full_text = %s,
                            extraction_status = %s,
                            extraction_method = %s,
                            extracted_at = now(),
                            image_url = %s,
                            image_source = %s
                        WHERE id = %s
                        """,
                        (
                            full_text,
                            status,
                            method,
                            image_url,
                            image_source,
                            article_id,
                        ),
                    )
                else:
                    cur.execute(
                        """
                        UPDATE articles
                        SET full_text = %s,
                            extraction_status = %s,
                            extraction_method = %s,
                            extracted_at = now(),
                            image_url = COALESCE(image_url, %s),
                            image_source = COALESCE(image_source, %s)
                        WHERE id = %s
                        """,
                        (
                            full_text,
                            status,
                            method,
                            image_url,
                            image_source,
                            article_id,
                        ),
                    )
            else:
                cur.execute(
                    """
                    UPDATE articles
                    SET full_text = %s, extraction_status = %s, extraction_method = %s,
                        extracted_at = now()
                    WHERE id = %s
                    """,
                    (full_text, status, method, article_id),
                )
        conn.commit()
    finally:
        return_connection(conn)


def abandon_stale_pending_articles(older_than_hours: int) -> int:
    """Mark articles stuck in 'pending' extraction as failed due to timeout.

    Articles with extraction_status = 'pending' and fetched_at older than
    older_than_hours are updated to extraction_status = 'extraction_failed'
    with extraction_method = 'timeout'. Returns the count of rows updated.

    This unblocks the cluster gate when dead URLs (paywalled, 404, redirected)
    would otherwise keep pending count > 0 indefinitely.
    """
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE articles SET extraction_status = 'extraction_failed', extraction_method = 'timeout' "
                "WHERE extraction_status = 'pending' "
                "AND (fetched_at IS NULL OR fetched_at < NOW() - %s::interval)",
                (f"{older_than_hours} hours",),
            )
            count = cur.rowcount
        conn.commit()
        return count
    finally:
        return_connection(conn)


def update_article_type(article_id: str, article_type: str) -> None:
    """Set article_type for an article. Values: 'news' or 'non_news'.

    When restoring a non_news article to 'news', also resets extraction_status
    to 'pending' so the enrichment pipeline picks it up on the next run.
    """
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            if article_type == "news":
                cur.execute(
                    """
                    UPDATE articles
                    SET article_type = %s,
                        extraction_status = CASE
                            WHEN extraction_status NOT IN ('extracted', 'skipped') THEN 'pending'
                            ELSE extraction_status
                        END
                    WHERE id = %s
                    """,
                    (article_type, article_id),
                )
            else:
                cur.execute(
                    "UPDATE articles SET article_type = %s WHERE id = %s",
                    (article_type, article_id),
                )
        conn.commit()
    finally:
        return_connection(conn)


def count_non_news_today() -> int:
    """Return count of non_news articles fetched today."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT COUNT(*) FROM articles
                WHERE article_type = 'non_news'
                  AND fetched_at::date = CURRENT_DATE
                """
            )
            row = cur.fetchone()
            return int(row[0]) if row else 0
    finally:
        return_connection(conn)


def get_recent_articles(
    since: datetime,
    source_id: str | None = None,
) -> list[dict[str, Any]]:
    """Return articles published on or after since, optionally filtered by source."""
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            if source_id:
                cur.execute(
                    """
                    SELECT * FROM articles
                    WHERE published_at >= %s AND source_id = %s
                    ORDER BY published_at DESC
                    """,
                    (since, source_id),
                )
            else:
                cur.execute(
                    """
                    SELECT * FROM articles
                    WHERE published_at >= %s
                    ORDER BY published_at DESC
                    """,
                    (since,),
                )
            return [dict(row) for row in cur.fetchall()]
    finally:
        return_connection(conn)
