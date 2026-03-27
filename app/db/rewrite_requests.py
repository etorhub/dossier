"""Rewrite request queue: enqueue on-demand rewrites from web, process in worker."""

from datetime import UTC, datetime
from typing import Any

import psycopg2.extras

from app.db.connection import get_connection, return_connection


def enqueue_rewrite(user_id: int) -> int | None:
    """Insert a pending rewrite request. Returns the new id, or None if skipped (idempotent).

    Skips insertion if a pending or processing request already exists for this user.
    """
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            # Check for existing pending/processing request
            cur.execute(
                """
                SELECT id FROM rewrite_requests
                WHERE user_id = %s AND status IN ('pending', 'processing')
                LIMIT 1
                """,
                (user_id,),
            )
            if cur.fetchone() is not None:
                return None

            cur.execute(
                """
                INSERT INTO rewrite_requests (user_id, status)
                VALUES (%s, 'pending')
                RETURNING id
                """,
                (user_id,),
            )
            row = cur.fetchone()
            assert row is not None
            request_id: int = row[0]
        conn.commit()
        return request_id
    finally:
        return_connection(conn)


def claim_pending_requests() -> list[dict[str, Any]]:
    """Atomically claim pending requests for processing. Returns list of claimed rows.

    Uses FOR UPDATE SKIP LOCKED to avoid races when multiple workers exist.
    """
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                WITH claimed AS (
                    SELECT id, user_id
                    FROM rewrite_requests
                    WHERE status = 'pending'
                    ORDER BY created_at ASC
                    FOR UPDATE SKIP LOCKED
                )
                UPDATE rewrite_requests r
                SET status = 'processing', started_at = NOW()
                FROM claimed c
                WHERE r.id = c.id
                RETURNING r.id, r.user_id
                """
            )
            rows = cur.fetchall()
        conn.commit()
        return [dict(row) for row in rows]
    finally:
        return_connection(conn)


def mark_done(request_id: int) -> None:
    """Mark a rewrite request as completed."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE rewrite_requests
                SET status = 'done', completed_at = %s
                WHERE id = %s
                """,
                (datetime.now(UTC), request_id),
            )
        conn.commit()
    finally:
        return_connection(conn)


def mark_failed(request_id: int, error: str) -> None:
    """Mark a rewrite request as failed with an error message."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE rewrite_requests
                SET status = 'failed', completed_at = %s, error_message = %s
                WHERE id = %s
                """,
                (datetime.now(UTC), error[:1000], request_id),
            )
        conn.commit()
    finally:
        return_connection(conn)
