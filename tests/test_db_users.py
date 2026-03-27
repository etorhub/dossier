"""Tests for app/db/users.py.

Uses a real database when DATABASE_URL is set (e.g. in Docker / CI with Postgres).
All tests are skipped when no database is available.
"""

from __future__ import annotations

import uuid

import pytest

from app.db import users as db_users
from app.db.connection import get_connection, return_connection


def _has_db() -> bool:
    try:
        conn = get_connection()
        return_connection(conn)
        return True
    except Exception:
        return False


_SKIP = pytest.mark.skipif(not _has_db(), reason="Database not available")


def _unique_email() -> str:
    return f"test_{uuid.uuid4().hex[:8]}@example.com"


def _cleanup_user(user_id: int) -> None:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM user_topics WHERE user_id = %s", (user_id,))
            cur.execute("DELETE FROM user_profiles WHERE user_id = %s", (user_id,))
            cur.execute("DELETE FROM users WHERE id = %s", (user_id,))
        conn.commit()
    finally:
        return_connection(conn)


# ---------------------------------------------------------------------------
# create_user / get_user_by_email / get_user_by_id
# ---------------------------------------------------------------------------


@_SKIP
def test_create_user_returns_integer_id() -> None:
    """create_user returns a positive integer id."""
    email = _unique_email()
    uid = db_users.create_user(email, "hashed_pw")
    try:
        assert isinstance(uid, int)
        assert uid > 0
    finally:
        _cleanup_user(uid)


@_SKIP
def test_get_user_by_email_returns_correct_row() -> None:
    """get_user_by_email returns a dict with the expected email."""
    email = _unique_email()
    uid = db_users.create_user(email, "hashed_pw")
    try:
        row = db_users.get_user_by_email(email)
        assert row is not None
        assert row["email"] == email
        assert row["id"] == uid
    finally:
        _cleanup_user(uid)


@_SKIP
def test_get_user_by_email_returns_none_for_unknown_email() -> None:
    """get_user_by_email returns None when the email is not found."""
    result = db_users.get_user_by_email("nobody_xyz_@example.com")
    assert result is None


@_SKIP
def test_get_user_by_id_returns_correct_row() -> None:
    """get_user_by_id returns a dict with the expected id."""
    email = _unique_email()
    uid = db_users.create_user(email, "hashed_pw")
    try:
        row = db_users.get_user_by_id(uid)
        assert row is not None
        assert row["id"] == uid
        assert row["email"] == email
    finally:
        _cleanup_user(uid)


@_SKIP
def test_get_user_by_id_returns_none_for_unknown_id() -> None:
    """get_user_by_id returns None for a non-existent id."""
    result = db_users.get_user_by_id(999_999_999)
    assert result is None


@_SKIP
def test_new_user_is_active_by_default() -> None:
    """Newly created users have is_active = True."""
    email = _unique_email()
    uid = db_users.create_user(email, "hashed_pw")
    try:
        row = db_users.get_user_by_id(uid)
        assert row is not None
        assert row["is_active"] is True
    finally:
        _cleanup_user(uid)


@_SKIP
def test_new_user_is_not_admin_by_default() -> None:
    """Newly created users have is_admin = False."""
    email = _unique_email()
    uid = db_users.create_user(email, "hashed_pw")
    try:
        row = db_users.get_user_by_id(uid)
        assert row is not None
        assert row["is_admin"] is False
    finally:
        _cleanup_user(uid)


# ---------------------------------------------------------------------------
# create_profile / get_profile / update_profile
# ---------------------------------------------------------------------------


@_SKIP
def test_create_and_get_profile() -> None:
    """create_profile stores the profile; get_profile retrieves it."""
    email = _unique_email()
    uid = db_users.create_user(email, "hashed_pw")
    try:
        data = {"location": "Barcelona", "language": "ca", "high_contrast": True}
        db_users.create_profile(uid, data)
        profile = db_users.get_profile(uid)
        assert profile is not None
        assert profile["location"] == "Barcelona"
        assert profile["language"] == "ca"
        assert profile["high_contrast"] is True
    finally:
        _cleanup_user(uid)


@_SKIP
def test_get_profile_returns_none_when_missing() -> None:
    """get_profile returns None when no profile exists for a user_id."""
    email = _unique_email()
    uid = db_users.create_user(email, "hashed_pw")
    try:
        result = db_users.get_profile(uid)
        assert result is None
    finally:
        _cleanup_user(uid)


@_SKIP
def test_update_profile_changes_fields() -> None:
    """update_profile modifies an existing profile."""
    email = _unique_email()
    uid = db_users.create_user(email, "hashed_pw")
    try:
        db_users.create_profile(uid, {"language": "ca"})
        db_users.update_profile(uid, {"language": "es"})
        profile = db_users.get_profile(uid)
        assert profile is not None
        assert profile["language"] == "es"
    finally:
        _cleanup_user(uid)


@_SKIP
def test_update_profile_clears_color_scheme_to_null() -> None:
    """update_profile with color_scheme=None sets the field to NULL (follow-system)."""
    email = _unique_email()
    uid = db_users.create_user(email, "hashed_pw")
    try:
        db_users.create_profile(uid, {"color_scheme": "dark"})
        db_users.update_profile(uid, {"color_scheme": None})
        profile = db_users.get_profile(uid)
        assert profile is not None
        assert profile["color_scheme"] is None
    finally:
        _cleanup_user(uid)


# ---------------------------------------------------------------------------
# set_user_topics / get_user_topics
# ---------------------------------------------------------------------------


@_SKIP
def test_set_and_get_user_topics() -> None:
    """set_user_topics stores topics; get_user_topics returns them in sorted order."""
    email = _unique_email()
    uid = db_users.create_user(email, "hashed_pw")
    try:
        db_users.set_user_topics(uid, ["technology", "general"])
        topics = db_users.get_user_topics(uid)
        assert sorted(topics) == ["general", "technology"]
    finally:
        _cleanup_user(uid)


@_SKIP
def test_set_user_topics_replaces_existing() -> None:
    """set_user_topics replaces the previous selection."""
    email = _unique_email()
    uid = db_users.create_user(email, "hashed_pw")
    try:
        db_users.set_user_topics(uid, ["general", "sports"])
        db_users.set_user_topics(uid, ["technology"])
        topics = db_users.get_user_topics(uid)
        assert topics == ["technology"]
    finally:
        _cleanup_user(uid)


@_SKIP
def test_get_user_topics_returns_empty_when_none_set() -> None:
    """get_user_topics returns an empty list when no topics are stored."""
    email = _unique_email()
    uid = db_users.create_user(email, "hashed_pw")
    try:
        topics = db_users.get_user_topics(uid)
        assert topics == []
    finally:
        _cleanup_user(uid)


# ---------------------------------------------------------------------------
# update_last_login
# ---------------------------------------------------------------------------


@_SKIP
def test_update_last_login_sets_timestamp() -> None:
    """update_last_login sets last_login_at to a non-null value."""
    email = _unique_email()
    uid = db_users.create_user(email, "hashed_pw")
    try:
        row_before = db_users.get_user_by_id(uid)
        assert row_before is not None
        assert row_before["last_login_at"] is None

        db_users.update_last_login(uid)

        row_after = db_users.get_user_by_id(uid)
        assert row_after is not None
        assert row_after["last_login_at"] is not None
    finally:
        _cleanup_user(uid)


# ---------------------------------------------------------------------------
# set_admin
# ---------------------------------------------------------------------------


@_SKIP
def test_set_admin_grants_and_revokes_admin_flag() -> None:
    """set_admin correctly toggles the is_admin flag."""
    email = _unique_email()
    uid = db_users.create_user(email, "hashed_pw")
    try:
        db_users.set_admin(uid, True)
        row = db_users.get_user_by_id(uid)
        assert row is not None
        assert row["is_admin"] is True

        db_users.set_admin(uid, False)
        row = db_users.get_user_by_id(uid)
        assert row is not None
        assert row["is_admin"] is False
    finally:
        _cleanup_user(uid)
