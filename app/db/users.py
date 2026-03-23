"""CRUD operations for users, user_profiles, and user_topics."""

from typing import Any

import psycopg2.extras

from app.db.connection import get_connection, return_connection


def create_user(email: str, password_hash: str) -> int:
    """Insert a user. Returns the new user id."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO users (email, password_hash)
                VALUES (%s, %s)
                RETURNING id
                """,
                (email, password_hash),
            )
            row = cur.fetchone()
            assert row is not None
            user_id: int = row[0]
        conn.commit()
        return user_id
    finally:
        return_connection(conn)


def get_user_by_email(email: str) -> dict[str, Any] | None:
    """Return user dict or None if not found."""
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """SELECT id, email, password_hash, is_active, is_admin,
                          created_at, last_login_at
                   FROM users WHERE email = %s""",
                (email,),
            )
            row = cur.fetchone()
            return dict(row) if row else None
    finally:
        return_connection(conn)


def get_user_by_id(user_id: int) -> dict[str, Any] | None:
    """Return user dict or None if not found."""
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """SELECT id, email, password_hash, is_active, is_admin,
                          created_at, last_login_at
                   FROM users WHERE id = %s""",
                (user_id,),
            )
            row = cur.fetchone()
            return dict(row) if row else None
    finally:
        return_connection(conn)


def create_profile(user_id: int, data: dict[str, Any]) -> None:
    """Insert a user profile."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO user_profiles (
                    user_id, location, language,
                    rewrite_tone, high_contrast, preferred_style,
                    color_scheme
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    user_id,
                    data.get("location"),
                    data.get("language", "ca"),
                    data.get(
                        "rewrite_tone",
                        "Journalistic style. Formal and well-written. Do not simplify; preserve original complexity and nuance. Avoid spoilers in headlines or summaries.",
                    ),
                    data.get("high_contrast", False),
                    data.get("preferred_style", "neutral"),
                    data.get("color_scheme") or None,
                ),
            )
        conn.commit()
    finally:
        return_connection(conn)


def update_profile(user_id: int, data: dict[str, Any]) -> None:
    """Update a user profile. Sets updated_at = now()."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE user_profiles
                SET
                    location = COALESCE(%s, location),
                    language = COALESCE(%s, language),
                    rewrite_tone = COALESCE(%s, rewrite_tone),
                    high_contrast = COALESCE(%s, high_contrast),
                    preferred_style = COALESCE(%s, preferred_style),
                    color_scheme = %s,  -- intentionally bare (not COALESCE): NULL means "follow system"
                    updated_at = now()
                WHERE user_id = %s
                """,
                (
                    data.get("location"),
                    data.get("language"),
                    data.get("rewrite_tone"),
                    data.get("high_contrast"),
                    data.get("preferred_style"),
                    data.get("color_scheme") or None,
                    user_id,
                ),
            )
        conn.commit()
    finally:
        return_connection(conn)


def get_profile(user_id: int) -> dict[str, Any] | None:
    """Return profile dict or None if not found."""
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT user_id, location, language,
                       rewrite_tone, high_contrast, preferred_style,
                       color_scheme, created_at, updated_at
                FROM user_profiles WHERE user_id = %s
                """,
                (user_id,),
            )
            row = cur.fetchone()
            return dict(row) if row else None
    finally:
        return_connection(conn)


def set_user_topics(user_id: int, topic_ids: list[str]) -> None:
    """Replace user's topic selections. Deletes existing, inserts new."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM user_topics WHERE user_id = %s", (user_id,))
            for topic_id in topic_ids:
                cur.execute(
                    "INSERT INTO user_topics (user_id, topic_id) VALUES (%s, %s)",
                    (user_id, topic_id),
                )
        conn.commit()
    finally:
        return_connection(conn)


def get_user_topics(user_id: int) -> list[str]:
    """Return list of enabled topic_ids for the user."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT topic_id FROM user_topics
                WHERE user_id = %s AND enabled = true
                ORDER BY topic_id
                """,
                (user_id,),
            )
            return [row[0] for row in cur.fetchall()]
    finally:
        return_connection(conn)


def update_last_login(user_id: int) -> None:
    """Update last_login_at for the user."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE users SET last_login_at = NOW() WHERE id = %s",
                (user_id,),
            )
        conn.commit()
    finally:
        return_connection(conn)


def set_admin(user_id: int, is_admin: bool) -> None:
    """Set is_admin flag for the user."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE users SET is_admin = %s WHERE id = %s",
                (is_admin, user_id),
            )
        conn.commit()
    finally:
        return_connection(conn)
