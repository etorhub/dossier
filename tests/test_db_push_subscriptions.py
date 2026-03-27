"""Tests for app/db/push_subscriptions.py.

Uses a real database when DATABASE_URL is set (e.g. in Docker / CI with Postgres).
All tests are skipped when no database is available.
"""

from __future__ import annotations

import uuid

import pytest

from app.db import push_subscriptions as push_db
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
    return f"push_test_{uuid.uuid4().hex[:8]}@example.com"


def _unique_endpoint() -> str:
    return f"https://push.example.com/{uuid.uuid4().hex}"


def _create_test_user_with_profile(language: str = "en") -> int:
    """Create a user + profile and return the user_id."""
    email = _unique_email()
    uid = db_users.create_user(email, "hashed_pw")
    db_users.create_profile(uid, {"language": language})
    return uid


def _cleanup(user_id: int, endpoint: str | None = None) -> None:
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            if endpoint:
                cur.execute("DELETE FROM push_subscriptions WHERE endpoint = %s", (endpoint,))
            else:
                cur.execute("DELETE FROM push_subscriptions WHERE user_id = %s", (user_id,))
            cur.execute("DELETE FROM user_topics WHERE user_id = %s", (user_id,))
            cur.execute("DELETE FROM user_profiles WHERE user_id = %s", (user_id,))
            cur.execute("DELETE FROM users WHERE id = %s", (user_id,))
        conn.commit()
    finally:
        return_connection(conn)


# ---------------------------------------------------------------------------
# save_subscription
# ---------------------------------------------------------------------------


@_SKIP
def test_save_subscription_inserts_new_row() -> None:
    """save_subscription inserts a new subscription row."""
    uid = _create_test_user_with_profile()
    endpoint = _unique_endpoint()
    try:
        push_db.save_subscription(uid, endpoint, "p256dh_key", "auth_token")
        subscriptions = push_db.get_all_subscriptions_with_language()
        endpoints = [s["endpoint"] for s in subscriptions]
        assert endpoint in endpoints
    finally:
        _cleanup(uid, endpoint)


@_SKIP
def test_save_subscription_upserts_on_duplicate_endpoint() -> None:
    """save_subscription updates keys when called twice with the same endpoint."""
    uid = _create_test_user_with_profile()
    endpoint = _unique_endpoint()
    try:
        push_db.save_subscription(uid, endpoint, "key_v1", "auth_v1")
        push_db.save_subscription(uid, endpoint, "key_v2", "auth_v2")

        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT p256dh FROM push_subscriptions WHERE endpoint = %s",
                    (endpoint,),
                )
                row = cur.fetchone()
        finally:
            return_connection(conn)

        assert row is not None
        assert row[0] == "key_v2"
    finally:
        _cleanup(uid, endpoint)


# ---------------------------------------------------------------------------
# delete_subscription
# ---------------------------------------------------------------------------


@_SKIP
def test_delete_subscription_removes_the_row() -> None:
    """delete_subscription removes the subscription row for the given endpoint."""
    uid = _create_test_user_with_profile()
    endpoint = _unique_endpoint()
    push_db.save_subscription(uid, endpoint, "k", "a")
    push_db.delete_subscription(endpoint)
    try:
        subscriptions = push_db.get_all_subscriptions_with_language()
        assert all(s["endpoint"] != endpoint for s in subscriptions)
    finally:
        _cleanup(uid)


@_SKIP
def test_delete_subscription_is_idempotent() -> None:
    """delete_subscription does not raise when called on a non-existent endpoint."""
    # Should not raise
    push_db.delete_subscription("https://nonexistent.example.com/endpoint")


# ---------------------------------------------------------------------------
# get_all_subscriptions_with_language
# ---------------------------------------------------------------------------


@_SKIP
def test_get_all_subscriptions_with_language_includes_user_language() -> None:
    """get_all_subscriptions_with_language joins user language from user_profiles."""
    uid = _create_test_user_with_profile(language="ca")
    endpoint = _unique_endpoint()
    try:
        push_db.save_subscription(uid, endpoint, "k", "a")
        subscriptions = push_db.get_all_subscriptions_with_language()
        match = next((s for s in subscriptions if s["endpoint"] == endpoint), None)
        assert match is not None
        assert match["language"] == "ca"
    finally:
        _cleanup(uid, endpoint)


@_SKIP
def test_get_all_subscriptions_with_language_returns_required_keys() -> None:
    """Every subscription dict contains endpoint, p256dh, auth, and language keys."""
    uid = _create_test_user_with_profile()
    endpoint = _unique_endpoint()
    try:
        push_db.save_subscription(uid, endpoint, "key", "auth")
        subscriptions = push_db.get_all_subscriptions_with_language()
        match = next((s for s in subscriptions if s["endpoint"] == endpoint), None)
        assert match is not None
        for key in ("endpoint", "p256dh", "auth", "language"):
            assert key in match
    finally:
        _cleanup(uid, endpoint)
