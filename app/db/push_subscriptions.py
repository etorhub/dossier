"""DB layer for push notification subscriptions."""

from __future__ import annotations

import logging
from typing import Any

from app.db.connection import get_connection, return_connection

logger = logging.getLogger(__name__)


def save_subscription(user_id: int, endpoint: str, p256dh: str, auth: str) -> None:
    """Insert or update a push subscription for a user."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO push_subscriptions (user_id, endpoint, p256dh, auth)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (endpoint) DO UPDATE
                    SET user_id = EXCLUDED.user_id,
                        p256dh = EXCLUDED.p256dh,
                        auth = EXCLUDED.auth
                """,
                (user_id, endpoint, p256dh, auth),
            )
        conn.commit()
    finally:
        return_connection(conn)


def delete_subscription(endpoint: str) -> None:
    """Remove a push subscription (e.g. when endpoint returns 410)."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM push_subscriptions WHERE endpoint = %s",
                (endpoint,),
            )
        conn.commit()
    finally:
        return_connection(conn)


def get_all_subscriptions_with_language() -> list[dict[str, Any]]:
    """Return all subscriptions joined with user language preference."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT ps.endpoint, ps.p256dh, ps.auth,
                       COALESCE(up.language, 'en') AS language
                FROM push_subscriptions ps
                JOIN user_profiles up ON up.user_id = ps.user_id
                """
            )
            rows = cur.fetchall()
            return [
                {"endpoint": r[0], "p256dh": r[1], "auth": r[2], "language": r[3]} for r in rows
            ]
    finally:
        return_connection(conn)
