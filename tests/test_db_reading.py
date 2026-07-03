"""Tests for per-user read-state DB logic in app/db/reading.py.

Uses a real database when DATABASE_URL is set (CI / Docker with Postgres).
All tests are skipped when no database is available.
"""

from __future__ import annotations

import contextlib
import uuid

import pytest

from app.db import reading as db_reading
from app.db import users as db_users
from app.db.connection import get_connection, return_connection


def _has_read_table() -> bool:
    conn = None
    try:
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute("SELECT user_id FROM user_read_stories LIMIT 0")
        conn.rollback()
        return_connection(conn)
        return True
    except Exception:
        if conn is not None:
            with contextlib.suppress(Exception):
                conn.rollback()
            return_connection(conn)
        return False


_SKIP = pytest.mark.skipif(
    not _has_read_table(),
    reason="Database not available or user_read_stories table missing",
)


def _unique_email() -> str:
    return f"reading_{uuid.uuid4().hex[:8]}@example.com"


def _create_story() -> str:
    """Insert a bare story row (satisfies the FK) and return its id."""
    story_id = str(uuid.uuid4())
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO stories (id) VALUES (%s::uuid)", (story_id,))
        conn.commit()
        return story_id
    finally:
        return_connection(conn)


def _cleanup(user_id: int, story_ids: list[str]) -> None:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM user_read_stories WHERE user_id = %s", (user_id,))
            for sid in story_ids:
                cur.execute("DELETE FROM stories WHERE id = %s::uuid", (sid,))
            cur.execute("DELETE FROM users WHERE id = %s", (user_id,))
        conn.commit()
    finally:
        return_connection(conn)


@_SKIP
def test_mark_story_read_inserts() -> None:
    """Marking a story read records it and get_read_story_ids returns it."""
    user_id = db_users.create_user(_unique_email(), "hashed")
    story_id = _create_story()
    try:
        db_reading.mark_story_read(user_id, story_id)
        assert db_reading.get_read_story_ids(user_id, [story_id]) == {story_id}
    finally:
        _cleanup(user_id, [story_id])


@_SKIP
def test_mark_story_read_is_idempotent() -> None:
    """Marking the same story twice does not raise and stays a single read."""
    user_id = db_users.create_user(_unique_email(), "hashed")
    story_id = _create_story()
    try:
        db_reading.mark_story_read(user_id, story_id)
        db_reading.mark_story_read(user_id, story_id)  # no error, no duplicate
        assert db_reading.get_read_story_ids(user_id, [story_id]) == {story_id}
    finally:
        _cleanup(user_id, [story_id])


@_SKIP
def test_get_read_story_ids_returns_only_read_subset() -> None:
    """get_read_story_ids returns only the stories the user has actually read."""
    user_id = db_users.create_user(_unique_email(), "hashed")
    read_story = _create_story()
    unread_story = _create_story()
    try:
        db_reading.mark_story_read(user_id, read_story)
        result = db_reading.get_read_story_ids(user_id, [read_story, unread_story])
        assert result == {read_story}
    finally:
        _cleanup(user_id, [read_story, unread_story])


def test_get_read_story_ids_empty_input_returns_empty_set() -> None:
    """An empty story_ids list short-circuits to an empty set (no DB call)."""
    assert db_reading.get_read_story_ids(1, []) == set()
