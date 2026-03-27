"""Admin dashboard queries: job runs, overview stats, feed health, incidents."""

import json
from datetime import UTC, datetime
from typing import Any

import psycopg2.extras

from app.db.connection import get_connection, return_connection


def insert_job_run(
    job_name: str,
    trigger: str = "scheduled",
    *,
    origin_hostname: str | None = None,
    origin_ip: str | None = None,
    origin_mode: str | None = None,
) -> int:
    """Insert a job run row. Returns the new id."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO job_runs (job_name, status, trigger,
                                      origin_hostname, origin_ip, origin_mode)
                VALUES (%s, 'running', %s, %s, %s, %s)
                RETURNING id
                """,
                (job_name, trigger, origin_hostname, origin_ip, origin_mode),
            )
            row = cur.fetchone()
            assert row is not None
            job_id: int = row[0]
        conn.commit()
        return job_id
    finally:
        return_connection(conn)


def update_job_run(
    job_id: int,
    *,
    status: str = "success",
    result: dict[str, Any] | None = None,
    error_message: str | None = None,
) -> None:
    """Update a job run with completion data."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE job_runs
                SET finished_at = NOW(),
                    duration_ms = EXTRACT(EPOCH FROM (NOW() - started_at)) * 1000,
                    status = %s,
                    result = %s,
                    error_message = %s
                WHERE id = %s
                """,
                (
                    status,
                    psycopg2.extras.Json(result) if result else None,
                    error_message,
                    job_id,
                ),
            )
        conn.commit()
    finally:
        return_connection(conn)


def get_recent_job_runs(limit: int = 20, job_name: str | None = None) -> list[dict[str, Any]]:
    """Return recent job runs, optionally filtered by job_name."""
    return get_job_runs_paginated(limit=limit, offset=0, job_name=job_name)


def get_job_runs_paginated(
    limit: int = 50,
    offset: int = 0,
    job_name: str | None = None,
    status: str | None = None,
) -> list[dict[str, Any]]:
    """Return paginated job runs with optional filters."""
    conn = get_connection()
    try:
        conditions: list[str] = []
        params: list[Any] = []
        if job_name:
            conditions.append("job_name = %s")
            params.append(job_name)
        if status:
            conditions.append("status = %s")
            params.append(status)
        where_clause = " AND ".join(conditions) if conditions else "TRUE"
        params.extend([limit, offset])

        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                f"""
                SELECT id, job_name, started_at, finished_at, duration_ms,
                       status, result, error_message, trigger,
                       origin_hostname, origin_ip, origin_mode
                FROM job_runs
                WHERE {where_clause}
                ORDER BY started_at DESC
                LIMIT %s OFFSET %s
                """,
                params,
            )
            return [dict(row) for row in cur.fetchall()]
    finally:
        return_connection(conn)


def get_job_runs_count(
    job_name: str | None = None,
    status: str | None = None,
) -> int:
    """Return total job runs count for pagination."""
    conn = get_connection()
    try:
        conditions: list[str] = []
        params: list[Any] = []
        if job_name:
            conditions.append("job_name = %s")
            params.append(job_name)
        if status:
            conditions.append("status = %s")
            params.append(status)
        where_clause = " AND ".join(conditions) if conditions else "TRUE"

        with conn.cursor() as cur:
            cur.execute(
                f"SELECT COUNT(*) FROM job_runs WHERE {where_clause}",
                params,
            )
            row = cur.fetchone()
            return row[0] if row else 0
    finally:
        return_connection(conn)


def get_last_job_run() -> dict[str, Any] | None:
    """Return the most recent job run across all jobs."""
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, job_name, started_at, finished_at, duration_ms,
                       status, result, error_message, trigger,
                       origin_hostname, origin_ip, origin_mode
                FROM job_runs
                ORDER BY started_at DESC
                LIMIT 1
                """
            )
            row = cur.fetchone()
            return dict(row) if row else None
    finally:
        return_connection(conn)


def get_job_run_by_id(job_id: int) -> dict[str, Any] | None:
    """Return a single job run by primary key."""
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, job_name, started_at, finished_at, duration_ms,
                       status, result, error_message, trigger,
                       origin_hostname, origin_ip, origin_mode
                FROM job_runs
                WHERE id = %s
                """,
                (job_id,),
            )
            row = cur.fetchone()
            return dict(row) if row else None
    finally:
        return_connection(conn)


def get_unfinished_job_run(job_name: str) -> dict[str, Any] | None:
    """Return the latest job run for this name that has not finished (still running or stuck)."""
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, job_name, started_at, finished_at, duration_ms,
                       status, result, error_message, trigger,
                       origin_hostname, origin_ip, origin_mode
                FROM job_runs
                WHERE job_name = %s AND finished_at IS NULL
                ORDER BY started_at DESC
                LIMIT 1
                """,
                (job_name,),
            )
            row = cur.fetchone()
            return dict(row) if row else None
    finally:
        return_connection(conn)


def get_overview_stats() -> dict[str, Any]:
    """Return overview counts for the dashboard."""
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM users) AS total_users,
                    (SELECT COUNT(*) FROM users WHERE is_active = true) AS active_users,
                    (SELECT COUNT(*) FROM articles
                     WHERE fetched_at::date = CURRENT_DATE) AS articles_today,
                    (SELECT COUNT(*) FROM articles
                     WHERE fetched_at::date = CURRENT_DATE
                       AND article_type = 'non_news') AS non_news_today,
                    (SELECT COUNT(*) FROM source_feeds WHERE feed_active = true) AS active_feeds,
                    (SELECT COUNT(*) FROM source_feeds) AS total_feeds
                """
            )
            row = cur.fetchone()
            stats = dict(row) if row else {}
            last_run = get_last_job_run()
            stats["last_job_run"] = last_run
            return stats
    finally:
        return_connection(conn)


def get_feed_health() -> list[dict[str, Any]]:
    """Return all feeds with source info for the feed health panel."""
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT sf.id, sf.source_id, sf.feed_url, sf.feed_label,
                       sf.feed_active, sf.consecutive_failures,
                       sf.last_fetched_at, sf.avg_articles_per_day,
                       sf.poll_interval_minutes,
                       sf.is_available, sf.last_availability_check_at,
                       ns.name AS source_name, ns.domain, ns.country_code,
                       ns.languages, ns.quality_score
                FROM source_feeds sf
                JOIN news_sources ns ON ns.id = sf.source_id
                ORDER BY sf.feed_active DESC, sf.consecutive_failures DESC,
                         sf.last_fetched_at DESC NULLS LAST
                """
            )
            return [dict(row) for row in cur.fetchall()]
    finally:
        return_connection(conn)


def get_article_pipeline_stats() -> dict[str, Any]:
    """Return extraction status breakdown and 7-day ingestion."""
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT extraction_status, COUNT(*) AS cnt
                FROM articles
                GROUP BY extraction_status
                """
            )
            by_status = {row["extraction_status"]: row["cnt"] for row in cur.fetchall()}

            cur.execute(
                """
                SELECT fetched_at::date AS day, COUNT(*) AS cnt
                FROM articles
                WHERE fetched_at >= CURRENT_DATE - INTERVAL '7 days'
                GROUP BY fetched_at::date
                ORDER BY day DESC
                """
            )
            by_day = [dict(row) for row in cur.fetchall()]

            return {"by_status": by_status, "by_day": by_day}
    finally:
        return_connection(conn)


def get_clustering_stats() -> dict[str, Any]:
    """Return story clustering and rewrite coverage stats."""
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT COUNT(*) AS cnt FROM stories")
            total_stories = cur.fetchone()["cnt"]

            cur.execute(
                """
                SELECT COUNT(DISTINCT article_id) AS cnt
                FROM story_articles
                """
            )
            articles_in_stories = cur.fetchone()["cnt"]

            cur.execute("SELECT COUNT(*) AS cnt FROM articles WHERE embedding IS NOT NULL")
            articles_with_embedding = cur.fetchone()["cnt"]

            cur.execute(
                """
                SELECT COUNT(DISTINCT story_id) AS cnt
                FROM story_rewrites
                WHERE rewrite_failed = false
                """
            )
            stories_with_rewrite = cur.fetchone()["cnt"]

            cur.execute(
                """
                SELECT COUNT(*) AS cnt
                FROM story_rewrites
                WHERE rewrite_failed = false
                """
            )
            rewrite_variants_ok = cur.fetchone()["cnt"]

            cur.execute(
                """
                SELECT style, language, COUNT(*) AS cnt
                FROM story_rewrites
                WHERE rewrite_failed = false
                GROUP BY style, language
                ORDER BY style, language
                """
            )
            rewrite_coverage_by_variant = [
                {
                    "style": row["style"],
                    "language": row["language"],
                    "count": row["cnt"],
                }
                for row in cur.fetchall()
            ]

            cur.execute(
                """
                SELECT COUNT(*) AS cnt
                FROM story_rewrites
                WHERE rewrite_failed = true
                  AND created_at >= NOW() - INTERVAL '24 hours'
                """
            )
            rewrite_failures_24h = cur.fetchone()["cnt"]

            return {
                "total_stories": total_stories,
                "articles_in_stories": articles_in_stories,
                "articles_with_embedding": articles_with_embedding,
                "stories_with_rewrite": stories_with_rewrite,
                "rewrite_variants_ok": rewrite_variants_ok,
                "rewrite_coverage_by_variant": rewrite_coverage_by_variant,
                "rewrite_failures_24h": rewrite_failures_24h,
            }
    finally:
        return_connection(conn)


def get_recent_rewrite_failures(hours: int = 24, limit: int = 50) -> list[dict[str, Any]]:
    """Return recent story rewrite failures with story_id, style, language, created_at,
    error_message."""
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT story_id::text, style, language, created_at, error_message
                FROM story_rewrites
                WHERE rewrite_failed = true
                  AND created_at >= NOW() - INTERVAL '1 hour' * %s
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (hours, limit),
            )
            return [dict(row) for row in cur.fetchall()]
    finally:
        return_connection(conn)


def get_rewrite_failure_diagnostics_24h() -> dict[str, Any]:
    """Failed rewrites in the last 24h: counts per variant and top error prefixes."""
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT style, language, COUNT(*) AS cnt
                FROM story_rewrites
                WHERE rewrite_failed = true
                  AND created_at >= NOW() - INTERVAL '24 hours'
                GROUP BY style, language
                ORDER BY cnt DESC, style, language
                """
            )
            by_variant = [
                {
                    "style": row["style"],
                    "language": row["language"],
                    "count": row["cnt"],
                }
                for row in cur.fetchall()
            ]

            cur.execute(
                """
                SELECT
                    SUBSTRING(
                        COALESCE(error_message, '(no message)')
                        FROM 1 FOR 120
                    ) AS error_prefix,
                    COUNT(*) AS cnt
                FROM story_rewrites
                WHERE rewrite_failed = true
                  AND created_at >= NOW() - INTERVAL '24 hours'
                GROUP BY 1
                ORDER BY cnt DESC
                LIMIT 15
                """
            )
            top_errors = [
                {
                    "error_prefix": row["error_prefix"],
                    "count": row["cnt"],
                }
                for row in cur.fetchall()
            ]

            return {"by_variant": by_variant, "top_errors": top_errors}
    finally:
        return_connection(conn)


def get_admin_users() -> list[dict[str, Any]]:
    """Return all users with profile info for the users panel."""
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT u.id, u.email, u.is_active, u.is_admin, u.created_at, u.last_login_at,
                       up.language
                FROM users u
                LEFT JOIN user_profiles up ON up.user_id = u.id
                ORDER BY u.created_at DESC
                """
            )
            return [dict(row) for row in cur.fetchall()]
    finally:
        return_connection(conn)


def get_incidents(config: dict[str, Any]) -> list[dict[str, Any]]:
    """Return auto-detected incidents for the incidents panel."""
    threshold = config.get("schedule", {}).get("fetcher", {}).get("circuit_breaker_threshold", 5)
    incidents: list[dict[str, Any]] = []

    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            # Feeds deactivated by circuit breaker
            cur.execute(
                """
                SELECT sf.id, sf.source_id, sf.feed_url, sf.consecutive_failures,
                       ns.name AS source_name
                FROM source_feeds sf
                JOIN news_sources ns ON ns.id = sf.source_id
                WHERE sf.feed_active = false AND sf.consecutive_failures >= %s
                """,
                (threshold,),
            )
            for row in cur.fetchall():
                incidents.append(
                    {
                        "type": "feed_deactivated",
                        "title": f"Feed deactivated: {row['source_name']}",
                        "detail": (
                            f"{row['feed_url']} — "
                            f"{row['consecutive_failures']} consecutive failures"
                        ),
                        "severity": "warning",
                    }
                )

            # Articles stuck in pending > 2 hours
            cur.execute(
                """
                SELECT COUNT(*) AS cnt
                FROM articles
                WHERE extraction_status = 'pending'
                  AND fetched_at < NOW() - INTERVAL '2 hours'
                """
            )
            pending_stuck = cur.fetchone()["cnt"]
            if pending_stuck > 0:
                incidents.append(
                    {
                        "type": "extraction_backlog",
                        "title": f"{pending_stuck} articles stuck in extraction",
                        "detail": "Articles pending for more than 2 hours",
                        "severity": "warning",
                    }
                )

            # Rewrite failures in last 24h
            cur.execute(
                """
                SELECT COUNT(*) AS cnt
                FROM story_rewrites
                WHERE rewrite_failed = true
                  AND created_at >= NOW() - INTERVAL '24 hours'
                """
            )
            rewrite_failures = cur.fetchone()["cnt"]
            if rewrite_failures > 0:
                incidents.append(
                    {
                        "type": "rewrite_failures",
                        "title": f"{rewrite_failures} rewrite failures in last 24h",
                        "detail": "Story rewrites failed",
                        "severity": "warning",
                    }
                )

            # Job runs with error in last 24h
            cur.execute(
                """
                SELECT id, job_name, started_at, error_message
                FROM job_runs
                WHERE status = 'error'
                  AND started_at >= NOW() - INTERVAL '24 hours'
                ORDER BY started_at DESC
                """
            )
            for row in cur.fetchall():
                incidents.append(
                    {
                        "type": "job_error",
                        "title": f"Job failed: {row['job_name']}",
                        "detail": row["error_message"] or "Unknown error",
                        "severity": "error",
                    }
                )
    finally:
        return_connection(conn)

    return incidents


def get_admin_articles(
    limit: int,
    offset: int,
    extraction_status: str | None = None,
    source_id: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    has_embedding: bool | None = None,
    in_story: bool | None = None,
    article_type: str | None = None,
) -> list[dict[str, Any]]:
    """Return articles for admin view with story_id, source_name, image_url, categories."""
    conn = get_connection()
    try:
        conditions: list[str] = []
        params: list[Any] = []
        if extraction_status:
            conditions.append("a.extraction_status = %s")
            params.append(extraction_status)
        if source_id:
            conditions.append("a.source_id = %s")
            params.append(source_id)
        if date_from:
            conditions.append("a.fetched_at::date >= %s::date")
            params.append(date_from)
        if date_to:
            conditions.append("a.fetched_at::date <= %s::date")
            params.append(date_to)
        if has_embedding is True:
            conditions.append("a.embedding IS NOT NULL")
        elif has_embedding is False:
            conditions.append("a.embedding IS NULL")
        if in_story is True:
            conditions.append("EXISTS (SELECT 1 FROM story_articles sa WHERE sa.article_id = a.id)")
        elif in_story is False:
            conditions.append(
                "NOT EXISTS (SELECT 1 FROM story_articles sa WHERE sa.article_id = a.id)"
            )
        if article_type:
            conditions.append("a.article_type = %s")
            params.append(article_type)
        where_clause = " AND ".join(conditions) if conditions else "TRUE"
        params.extend([limit, offset])

        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                f"""
                SELECT a.id, a.title, a.url, a.source_id, a.published_at,
                       a.fetched_at, a.extraction_status, a.extraction_method,
                       a.extracted_at, a.image_url, a.categories,
                       a.article_type,
                       (a.embedding IS NOT NULL) AS has_embedding,
                       sa.story_id::text AS story_id,
                       ns.name AS source_name
                FROM articles a
                LEFT JOIN news_sources ns ON ns.id = a.source_id
                LEFT JOIN story_articles sa ON sa.article_id = a.id
                WHERE {where_clause}
                ORDER BY a.fetched_at DESC NULLS LAST
                LIMIT %s OFFSET %s
                """,
                params,
            )
            return [dict(row) for row in cur.fetchall()]
    finally:
        return_connection(conn)


def get_admin_article_by_id(article_id: str) -> dict[str, Any] | None:
    """Return a single article by ID with full content (raw_text, full_text) for ops detail view."""
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT a.id, a.title, a.url, a.source_id, a.published_at,
                       a.fetched_at, a.raw_text, a.full_text, a.guid,
                       a.extraction_status, a.extraction_method, a.extracted_at,
                       a.image_url, a.image_source, a.categories,
                       (a.embedding IS NOT NULL) AS has_embedding,
                       sa.story_id::text AS story_id,
                       ns.name AS source_name
                FROM articles a
                LEFT JOIN news_sources ns ON ns.id = a.source_id
                LEFT JOIN story_articles sa ON sa.article_id = a.id
                WHERE a.id = %s
                LIMIT 1
                """,
                (article_id,),
            )
            row = cur.fetchone()
            return dict(row) if row else None
    finally:
        return_connection(conn)


def get_admin_articles_count(
    extraction_status: str | None = None,
    source_id: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    has_embedding: bool | None = None,
    in_story: bool | None = None,
    article_type: str | None = None,
) -> int:
    """Return total article count for admin pagination."""
    conn = get_connection()
    try:
        conditions: list[str] = []
        params: list[Any] = []
        if extraction_status:
            conditions.append("extraction_status = %s")
            params.append(extraction_status)
        if source_id:
            conditions.append("source_id = %s")
            params.append(source_id)
        if date_from:
            conditions.append("fetched_at::date >= %s::date")
            params.append(date_from)
        if date_to:
            conditions.append("fetched_at::date <= %s::date")
            params.append(date_to)
        if has_embedding is True:
            conditions.append("embedding IS NOT NULL")
        elif has_embedding is False:
            conditions.append("embedding IS NULL")
        if in_story is True:
            conditions.append(
                "EXISTS (SELECT 1 FROM story_articles sa WHERE sa.article_id = articles.id)"
            )
        elif in_story is False:
            conditions.append(
                "NOT EXISTS (SELECT 1 FROM story_articles sa WHERE sa.article_id = articles.id)"
            )
        if article_type:
            conditions.append("article_type = %s")
            params.append(article_type)
        where_clause = " AND ".join(conditions) if conditions else "TRUE"

        with conn.cursor() as cur:
            cur.execute(
                f"SELECT COUNT(*) FROM articles WHERE {where_clause}",
                params,
            )
            row = cur.fetchone()
            return row[0] if row else 0
    finally:
        return_connection(conn)


def override_article_type(article_id: str, article_type: str) -> bool:
    """Set article_type for an article. Returns True if the article was found.

    When restoring to 'news', also resets extraction_status to 'pending'
    (unless already extracted/skipped) so the article re-enters the pipeline.
    """
    from app.db import articles as articles_db  # avoid circular import

    articles_db.update_article_type(article_id, article_type)
    return True


def scan_and_mark_non_news() -> int:
    """Run classifier over all 'news' articles and mark detected non-news.

    Returns the count of articles re-classified as non_news.
    Used for retroactive cleanup of already-ingested content.
    """
    from app.feed.classifier import classify_article

    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, title, COALESCE(full_text, raw_text, '') AS text
                FROM articles
                WHERE article_type = 'news'
                ORDER BY fetched_at DESC
                """
            )
            rows = [dict(r) for r in cur.fetchall()]
    finally:
        return_connection(conn)

    flagged: list[str] = []
    for row in rows:
        if classify_article(row["title"] or "", row["text"] or "") == "non_news":
            flagged.append(row["id"])

    if not flagged:
        return 0

    conn2 = get_connection()
    try:
        with conn2.cursor() as cur:
            cur.execute(
                "UPDATE articles SET article_type = 'non_news' WHERE id = ANY(%s)",
                (flagged,),
            )
        conn2.commit()
    finally:
        return_connection(conn2)

    return len(flagged)


def get_admin_stories(limit: int, offset: int) -> list[dict[str, Any]]:
    """Return stories with article_count and sample_titles for admin view."""
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT s.id::text AS story_id, s.created_at,
                       COUNT(sa.article_id) AS article_count,
                       (
                         SELECT COALESCE(array_agg(t.title), ARRAY[]::text[])
                         FROM (
                           SELECT a.title
                           FROM story_articles sa2
                           JOIN articles a ON a.id = sa2.article_id
                           WHERE sa2.story_id = s.id
                           ORDER BY sa2.position
                           LIMIT 3
                         ) t
                       ) AS sample_titles
                FROM stories s
                LEFT JOIN story_articles sa ON sa.story_id = s.id
                GROUP BY s.id
                ORDER BY s.created_at DESC
                LIMIT %s OFFSET %s
                """,
                (limit, offset),
            )
            rows = cur.fetchall()
            result: list[dict[str, Any]] = []
            for row in rows:
                d = dict(row)
                # sample_titles may be a list from array_agg; limit to 3
                titles = d.get("sample_titles")
                if titles is not None and not isinstance(titles, list):
                    titles = list(titles) if titles else []
                d["sample_titles"] = (titles or [])[:3]
                result.append(d)
            return result
    finally:
        return_connection(conn)


def get_admin_stories_count(story_id: str | None = None) -> int:
    """Return total story count for admin pagination (optionally one story by UUID)."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            if story_id:
                cur.execute(
                    "SELECT COUNT(*) FROM stories WHERE id = %s::uuid",
                    (story_id,),
                )
            else:
                cur.execute("SELECT COUNT(*) FROM stories")
            row = cur.fetchone()
            return row[0] if row else 0
    finally:
        return_connection(conn)


def get_admin_story_articles(story_id: str) -> list[dict[str, Any]]:
    """Return articles in a story with source_name for admin story detail view."""
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT a.id, a.title, a.url, a.source_id, sa.position,
                       ns.name AS source_name
                FROM articles a
                JOIN story_articles sa ON sa.article_id = a.id
                LEFT JOIN news_sources ns ON ns.id = a.source_id
                WHERE sa.story_id = %s::uuid
                ORDER BY sa.position
                """,
                (story_id,),
            )
            return [dict(row) for row in cur.fetchall()]
    finally:
        return_connection(conn)


def flag_article_not_in_story(article_id: str, story_id: str) -> dict[str, Any] | None:
    """Remove article from story, record clustering_feedback, recompute story centroid.

    Sets stories.needs_rewrite so the next rewrite batch regenerates this story from the
    remaining sources (full cascade). Stories with needs_rewrite bypass the rewrite time
    window so they are not skipped when all member articles are older than cluster_window.

    Returns the new feedback row (with string UUID id), or None if the article was not in the story.
    """
    from app.clustering.vectors import (
        cosine_similarity,
        embedding_from_article,
        recompute_story_centroid,
    )
    from app.db import articles as articles_db
    from app.db import stories as stories_db

    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT 1 FROM story_articles
                WHERE story_id = %s::uuid AND article_id = %s
                """,
                (story_id, article_id),
            )
            if cur.fetchone() is None:
                return None

            article = articles_db.get_article_by_id(article_id)
            if not article:
                return None

            cur.execute(
                "SELECT centroid_embedding FROM stories WHERE id = %s::uuid",
                (story_id,),
            )
            row = cur.fetchone()
            centroid_raw = row["centroid_embedding"] if row else None
            centroid_list: list[float] | None = None
            if centroid_raw is not None:
                if isinstance(centroid_raw, list):
                    centroid_list = centroid_raw
                elif isinstance(centroid_raw, str):
                    try:
                        centroid_list = json.loads(centroid_raw)
                    except json.JSONDecodeError:
                        centroid_list = None

            emb = embedding_from_article(article)
            sim: float | None = None
            if emb and centroid_list:
                sim = float(cosine_similarity(emb, centroid_list))

            art_snap = emb
            cen_snap = centroid_list

            cur.execute(
                """
                INSERT INTO clustering_feedback (
                    article_id, story_id, similarity_at_flag,
                    article_embedding_snapshot, story_centroid_snapshot, status
                )
                VALUES (%s, %s::uuid, %s, %s::jsonb, %s::jsonb, 'pending')
                RETURNING id, article_id, story_id::text, similarity_at_flag, status, flagged_at
                """,
                (
                    article_id,
                    story_id,
                    sim,
                    psycopg2.extras.Json(art_snap) if art_snap is not None else None,
                    psycopg2.extras.Json(cen_snap) if cen_snap is not None else None,
                ),
            )
            fb_row = cur.fetchone()
            if fb_row is None:
                return None

            cur.execute(
                """
                DELETE FROM story_articles
                WHERE story_id = %s::uuid AND article_id = %s
                """,
                (story_id, article_id),
            )
        conn.commit()
        out = dict(fb_row)
        out["id"] = str(out["id"])
        out["story_id"] = str(out["story_id"])
    finally:
        return_connection(conn)

    recompute_story_centroid(story_id)
    stories_db.set_story_needs_rewrite(story_id, True)
    return out


def get_clustering_feedback(
    *,
    status: str | None = None,
    statuses: list[str] | None = None,
    limit: int = 100,
    offset: int = 0,
    order: str = "flagged_desc",
) -> list[dict[str, Any]]:
    """List clustering feedback rows with article title for ops UI.

    order: ``flagged_desc`` (newest first, default for ops table) or
    ``retry_asc`` (pending then failed, oldest flagged first — for the agent).
    """
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            if statuses:
                where = "WHERE cf.status = ANY(%s)"
                params_head: list[Any] = [statuses]
            elif status:
                where = "WHERE cf.status = %s"
                params_head = [status]
            else:
                where = ""
                params_head = []

            if order == "retry_asc":
                order_clause = (
                    "ORDER BY CASE cf.status WHEN 'pending' THEN 0 WHEN 'failed' THEN 1 "
                    "ELSE 2 END, cf.flagged_at ASC"
                )
            else:
                order_clause = "ORDER BY cf.flagged_at DESC"

            params = [*params_head, limit, offset]
            cur.execute(
                f"""
                SELECT cf.id, cf.article_id, cf.story_id::text AS story_id,
                       cf.similarity_at_flag, cf.status,
                       cf.agent_analysis, cf.agent_recommendation,
                       cf.flagged_at, cf.reviewed_at,
                       a.title AS article_title
                FROM clustering_feedback cf
                JOIN articles a ON a.id = cf.article_id
                {where}
                {order_clause}
                LIMIT %s OFFSET %s
                """,
                tuple(params),
            )
            rows = []
            for row in cur.fetchall():
                d = dict(row)
                d["id"] = str(d["id"])
                rows.append(d)
            return rows
    finally:
        return_connection(conn)


def get_pending_clustering_feedback() -> list[dict[str, Any]]:
    """Return feedback rows for the review agent (pending or failed, retryable)."""
    return get_clustering_feedback(
        statuses=["pending", "failed"],
        limit=500,
        offset=0,
        order="retry_asc",
    )


def get_clustering_feedback_flagged_article_id(feedback_id: str) -> str | None:
    """Return the flagged article_id for a clustering_feedback row, if it exists."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT article_id FROM clustering_feedback WHERE id = %s::uuid",
                (feedback_id,),
            )
            row = cur.fetchone()
            if not row or row[0] is None:
                return None
            return str(row[0])
    finally:
        return_connection(conn)


def get_active_exclusion_rules() -> list[dict[str, Any]]:
    """Return active clustering exclusion rules for the clustering service."""
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, rule_type, rule_data, description, feedback_id
                FROM clustering_exclusion_rules
                WHERE active = true
                ORDER BY created_at ASC
                """
            )
            rows = []
            for row in cur.fetchall():
                d = dict(row)
                d["id"] = str(d["id"])
                fid = d.get("feedback_id")
                d["feedback_id"] = str(fid) if fid is not None else None
                rd = d.get("rule_data")
                if isinstance(rd, str):
                    try:
                        d["rule_data"] = json.loads(rd)
                    except json.JSONDecodeError:
                        d["rule_data"] = {}
                rows.append(d)
            return rows
    finally:
        return_connection(conn)


def update_clustering_feedback_review(
    feedback_id: str,
    *,
    status: str,
    agent_analysis: str | None,
    agent_recommendation: str | None,
) -> None:
    """Set feedback status after agent run (reviewed, failed, dismissed, etc.).

    Use ``failed`` for errors so ``review-clustering`` can retry the row.
    """
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE clustering_feedback
                SET status = %s,
                    agent_analysis = %s,
                    agent_recommendation = %s,
                    reviewed_at = %s
                WHERE id = %s::uuid
                """,
                (
                    status,
                    agent_analysis,
                    agent_recommendation,
                    datetime.now(UTC),
                    feedback_id,
                ),
            )
        conn.commit()
    finally:
        return_connection(conn)


def insert_clustering_exclusion_rule(
    feedback_id: str | None,
    rule_type: str,
    rule_data: dict[str, Any],
    description: str | None,
) -> str:
    """Insert an exclusion rule. Returns new rule id as string."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO clustering_exclusion_rules (
                    feedback_id, rule_type, rule_data, description, active
                )
                VALUES (%s, %s, %s::jsonb, %s, true)
                RETURNING id
                """,
                (
                    feedback_id,
                    rule_type,
                    psycopg2.extras.Json(rule_data),
                    description,
                ),
            )
            row = cur.fetchone()
            assert row is not None
            rid = str(row[0])
        conn.commit()
        return rid
    finally:
        return_connection(conn)


def get_stories_with_rewrite_status(
    limit: int,
    offset: int,
    config: dict[str, Any],
    story_id: str | None = None,
) -> list[dict[str, Any]]:
    """Return stories with article_count, sample_titles, and rewrite status matrix.

    rewrite_matrix: dict mapping (style, language) -> "done" | "failed" | "missing"
    """
    styles = [s["id"] for s in config.get("rewriting", {}).get("styles", [])]
    languages = [lang["id"] for lang in config.get("rewriting", {}).get("languages", [])]
    if not styles:
        styles = ["neutral"]
    if not languages:
        languages = ["ca", "es", "en"]

    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            where_story = "WHERE s.id = %s::uuid" if story_id else ""
            params: list[Any] = []
            if story_id:
                params.append(story_id)
            params.extend([limit, offset])
            cur.execute(
                f"""
                SELECT s.id::text AS story_id, s.created_at,
                       COUNT(sa.article_id) AS article_count,
                       (
                         SELECT COALESCE(array_agg(t.title), ARRAY[]::text[])
                         FROM (
                           SELECT a.title
                           FROM story_articles sa2
                           JOIN articles a ON a.id = sa2.article_id
                           WHERE sa2.story_id = s.id
                           ORDER BY sa2.position
                           LIMIT 3
                         ) t
                       ) AS sample_titles
                FROM stories s
                LEFT JOIN story_articles sa ON sa.story_id = s.id
                {where_story}
                GROUP BY s.id
                ORDER BY s.created_at DESC
                LIMIT %s OFFSET %s
                """,
                tuple(params),
            )
            stories = [dict(row) for row in cur.fetchall()]

            if not stories:
                return []

            story_ids = [s["story_id"] for s in stories]
            cur.execute(
                """
                SELECT story_id::text, style, language, rewrite_failed
                FROM story_rewrites
                WHERE story_id::text = ANY(%s)
                """,
                (story_ids,),
            )
            rewrites = [dict(row) for row in cur.fetchall()]

        rewrite_by_story: dict[str, dict[str, str]] = {}
        for s in stories:
            rewrite_by_story[s["story_id"]] = {}
            for st in styles:
                for lang in languages:
                    rewrite_by_story[s["story_id"]][f"{st}:{lang}"] = "missing"

        for r in rewrites:
            sid = r["story_id"]
            key = f"{r['style']}:{r['language']}"
            if sid in rewrite_by_story and key in rewrite_by_story[sid]:
                rewrite_by_story[sid][key] = "failed" if r["rewrite_failed"] else "done"

        for s in stories:
            titles = s.get("sample_titles")
            if titles is not None and not isinstance(titles, list):
                titles = list(titles) if titles else []
            s["sample_titles"] = (titles or [])[:3]
            s["rewrite_matrix"] = rewrite_by_story.get(s["story_id"], {})
            s["styles"] = styles
            s["languages"] = languages

        return stories
    finally:
        return_connection(conn)


def get_user_usage_stats() -> list[dict[str, Any]]:
    """Return users with profile info, read_stories count, and topic selections."""
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT u.id, u.email, u.is_active, u.is_admin, u.created_at, u.last_login_at,
                       up.language, up.preferred_style, up.rewrite_tone, up.location,
                       (SELECT COUNT(*) FROM user_read_stories urs
                        WHERE urs.user_id = u.id) AS read_stories_count,
                       (SELECT COALESCE(
                            array_agg(ut.topic_id ORDER BY ut.topic_id),
                            ARRAY[]::text[]
                        ) FROM user_topics ut
                        WHERE ut.user_id = u.id AND ut.enabled = true) AS enabled_topics
                FROM users u
                LEFT JOIN user_profiles up ON up.user_id = u.id
                ORDER BY u.created_at DESC
                """
            )
            rows = cur.fetchall()
            result: list[dict[str, Any]] = []
            for row in rows:
                d = dict(row)
                topics = d.get("enabled_topics")
                if topics is not None and not isinstance(topics, list):
                    topics = list(topics) if topics else []
                d["enabled_topics"] = topics or []
                result.append(d)
            return result
    finally:
        return_connection(conn)
