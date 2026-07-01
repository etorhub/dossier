"""Tests for the reading streak DB logic in app/db/users.py.

Uses a real database when DATABASE_URL is set (CI / Docker with Postgres).
All tests are skipped when no database is available.
"""

from __future__ import annotations

import contextlib
import uuid
from datetime import date, timedelta

import pytest

from app.db import users as db_users
from app.db.connection import get_connection, return_connection


def _has_streak_columns() -> bool:
    conn = None
    try:
        conn = get_connection()
        with conn.cursor() as cur:
            cur.execute("SELECT reading_streak FROM user_profiles LIMIT 0")
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
    not _has_streak_columns(),
    reason="Database not available or migration 035 not applied",
)


def _pg_today() -> date:
    """Return PostgreSQL's current date so tests use the same calendar as the SQL."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT CURRENT_DATE")
            result = cur.fetchone()
        conn.rollback()
        return result[0]  # type: ignore[index]
    finally:
        return_connection(conn)


def _unique_email() -> str:
    return f"streak_{uuid.uuid4().hex[:8]}@example.com"


def _create_user_with_profile() -> int:
    user_id = db_users.create_user(_unique_email(), "hashed")
    db_users.create_profile(
        user_id,
        {
            "location": None,
            "language": "ca",
            "rewrite_tone": "neutral",
            "high_contrast": False,
            "preferred_style": "neutral",
            "color_scheme": None,
        },
    )
    return user_id


def _cleanup(user_id: int) -> None:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM user_topics WHERE user_id = %s", (user_id,))
            cur.execute("DELETE FROM user_profiles WHERE user_id = %s", (user_id,))
            cur.execute("DELETE FROM users WHERE id = %s", (user_id,))
        conn.commit()
    finally:
        return_connection(conn)


def _set_streak(
    user_id: int,
    reading_streak: int,
    longest_streak: int,
    last_read_date: date | None,
) -> None:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE user_profiles
                SET reading_streak = %s, longest_streak = %s, last_read_date = %s
                WHERE user_id = %s
                """,
                (reading_streak, longest_streak, last_read_date, user_id),
            )
        conn.commit()
    finally:
        return_connection(conn)


# ---------------------------------------------------------------------------
# update_reading_streak tests
# ---------------------------------------------------------------------------


@_SKIP
def test_streak_increments_on_first_read() -> None:
    """First-ever read sets streak to 1."""
    user_id = _create_user_with_profile()
    try:
        db_users.update_reading_streak(user_id)
        profile = db_users.get_profile(user_id)
        assert profile is not None
        assert profile["reading_streak"] == 1
        assert profile["longest_streak"] == 1
        assert profile["last_read_date"] == _pg_today()
    finally:
        _cleanup(user_id)


@_SKIP
def test_streak_idempotent_when_already_read_today() -> None:
    """Reading again on the same day does not change the streak count."""
    user_id = _create_user_with_profile()
    try:
        _set_streak(user_id, 5, 5, _pg_today())
        db_users.update_reading_streak(user_id)
        profile = db_users.get_profile(user_id)
        assert profile is not None
        assert profile["reading_streak"] == 5
    finally:
        _cleanup(user_id)


@_SKIP
def test_streak_increments_on_consecutive_day() -> None:
    """Reading on the day after last_read_date increments streak by 1."""
    user_id = _create_user_with_profile()
    try:
        yesterday = _pg_today() - timedelta(days=1)
        _set_streak(user_id, 6, 6, yesterday)
        db_users.update_reading_streak(user_id)
        profile = db_users.get_profile(user_id)
        assert profile is not None
        assert profile["reading_streak"] == 7
        assert profile["longest_streak"] == 7
    finally:
        _cleanup(user_id)


@_SKIP
def test_streak_resets_on_missed_day() -> None:
    """Missing one or more days resets streak to 1."""
    user_id = _create_user_with_profile()
    try:
        two_days_ago = _pg_today() - timedelta(days=2)
        _set_streak(user_id, 10, 10, two_days_ago)
        db_users.update_reading_streak(user_id)
        profile = db_users.get_profile(user_id)
        assert profile is not None
        assert profile["reading_streak"] == 1
        assert profile["longest_streak"] == 10
    finally:
        _cleanup(user_id)


@_SKIP
def test_longest_streak_updated_when_new_record() -> None:
    """longest_streak updates when current streak surpasses it."""
    user_id = _create_user_with_profile()
    try:
        yesterday = _pg_today() - timedelta(days=1)
        _set_streak(user_id, 14, 14, yesterday)
        db_users.update_reading_streak(user_id)
        profile = db_users.get_profile(user_id)
        assert profile is not None
        assert profile["reading_streak"] == 15
        assert profile["longest_streak"] == 15
    finally:
        _cleanup(user_id)
