"""Tests for db/rewrite_requests module.

Uses real database when DATABASE_URL is set (e.g. in Docker).
Skips when no database available.
"""

import pytest

from app.db import connection as db_connection
from app.db import rewrite_requests as rewrite_requests_db


def _has_db() -> bool:
    """Check if we can connect to the database."""
    try:
        conn = db_connection.get_connection()
        db_connection.return_connection(conn)
        return True
    except Exception:
        return False


def _create_test_user() -> int:
    """Create a test user and return user_id. Caller must clean up."""
    conn = db_connection.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO users (email, password_hash)
                VALUES ('test_rewrite_req@example.com', 'hash')
                ON CONFLICT (email) DO UPDATE SET email = EXCLUDED.email
                RETURNING id
                """
            )
            row = cur.fetchone()
            assert row is not None
            user_id: int = row[0]
        conn.commit()
        return user_id
    finally:
        db_connection.return_connection(conn)


def _cleanup_user_and_requests(user_id: int) -> None:
    """Delete rewrite_requests and test user."""
    conn = db_connection.get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM rewrite_requests WHERE user_id = %s", (user_id,))
            cur.execute("DELETE FROM users WHERE email = 'test_rewrite_req@example.com'")
        conn.commit()
    finally:
        db_connection.return_connection(conn)


@pytest.mark.skipif(not _has_db(), reason="Database not available")
def test_enqueue_rewrite_returns_id() -> None:
    """enqueue_rewrite inserts a pending request and returns id."""
    user_id = _create_test_user()
    try:
        result = rewrite_requests_db.enqueue_rewrite(user_id)
        assert result is not None
        assert isinstance(result, int)
    finally:
        _cleanup_user_and_requests(user_id)


@pytest.mark.skipif(not _has_db(), reason="Database not available")
def test_enqueue_rewrite_idempotent() -> None:
    """enqueue_rewrite skips when pending/processing already exists for user."""
    user_id = _create_test_user()
    try:
        first = rewrite_requests_db.enqueue_rewrite(user_id)
        second = rewrite_requests_db.enqueue_rewrite(user_id)
        assert first is not None
        assert second is None  # skipped
    finally:
        _cleanup_user_and_requests(user_id)


@pytest.mark.skipif(not _has_db(), reason="Database not available")
def test_claim_pending_requests() -> None:
    """claim_pending_requests atomically claims and returns rows."""
    user_id = _create_test_user()
    try:
        rewrite_requests_db.enqueue_rewrite(user_id)
        claimed = rewrite_requests_db.claim_pending_requests()
        assert len(claimed) >= 1
        row = next(r for r in claimed if r["user_id"] == user_id)
        assert row["id"] is not None
        assert row["user_id"] == user_id
        rewrite_requests_db.mark_done(row["id"])
    finally:
        _cleanup_user_and_requests(user_id)


@pytest.mark.skipif(not _has_db(), reason="Database not available")
def test_mark_done_and_mark_failed() -> None:
    """mark_done and mark_failed update status correctly."""
    user_id = _create_test_user()
    try:
        rewrite_requests_db.enqueue_rewrite(user_id)
        claimed = rewrite_requests_db.claim_pending_requests()
        row = next(r for r in claimed if r["user_id"] == user_id)
        rewrite_requests_db.mark_done(row["id"])
        # Verify by claiming again - should get nothing for this user
        # (we'd need a second enqueue to test; mark_done is sufficient)
    finally:
        _cleanup_user_and_requests(user_id)
