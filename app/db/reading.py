"""Per-user reading state: which stories a user has read.

Writes and reads the ``user_read_stories`` table (created in migration 010 as
``user_read_clusters``, renamed in 017). Used to drive the guided reading
session: track which stories are done and detect when the whole daily digest
has been completed.
"""

import contextlib

from app.db.connection import get_connection, return_connection


def mark_story_read(user_id: int, story_id: str) -> None:
    """Record that the user has read a story. Idempotent; never raises.

    A read-tracking failure must not break the article render, so this mirrors
    ``update_reading_streak`` and swallows/rolls back on error.
    """
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO user_read_stories (user_id, story_id)
                VALUES (%s, %s)
                ON CONFLICT (user_id, story_id) DO NOTHING
                """,
                (user_id, story_id),
            )
        conn.commit()
    except Exception:
        with contextlib.suppress(Exception):
            conn.rollback()
    finally:
        return_connection(conn)


def get_read_story_ids(user_id: int, story_ids: list[str]) -> set[str]:
    """Return the subset of ``story_ids`` the user has already read.

    Returns an empty set for an empty input or on error.
    """
    if not story_ids:
        return set()
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT story_id FROM user_read_stories
                WHERE user_id = %s AND story_id = ANY(%s::uuid[])
                """,
                (user_id, story_ids),
            )
            return {str(row[0]) for row in cur.fetchall()}
    except Exception:
        with contextlib.suppress(Exception):
            conn.rollback()
        return set()
    finally:
        return_connection(conn)
