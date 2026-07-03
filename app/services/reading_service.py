"""Guided reading session: walk the daily digest one story at a time.

The session presents the day's digest (``article_service.get_feed``) one
unread story at a time. A story is "read" once the user advances past it,
recorded in ``user_read_stories`` via ``app.db.reading``. When every story in
today's digest has been read, the digest is *complete* and the reading streak
advances (once per day, idempotent).
"""

from datetime import date
from typing import Any

from app.db import reading as db_reading
from app.db.users import update_reading_streak
from app.services import article_service, profile_service


def get_session_state(
    user_id: int,
    config: dict[str, Any],
    profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compute the current guided-session state for a user.

    Returns a dict with:
      - ``total``: number of stories in today's digest
      - ``read_count``: how many of them the user has already read
      - ``current``: the next unread story (hydrated for reading), or None
      - ``completed``: True when the whole digest has been read
      - ``rewrites_pending``: True when stories exist but rewrites aren't ready
      - ``profile``: the user's profile (for streak display)
    """
    if profile is None:
        profile = profile_service.get_profile_with_selections(user_id)

    feed, rewrites_pending = article_service.get_feed(user_id)
    story_ids = [s["id"] for s in feed]
    read_ids = db_reading.get_read_story_ids(user_id, story_ids)
    total = len(feed)
    read_count = sum(1 for sid in story_ids if sid in read_ids)

    current_summary: dict[str, Any] | None = None
    for story in feed:
        if story["id"] not in read_ids:
            current_summary = story
            break

    completed = total > 0 and current_summary is None

    current: dict[str, Any] | None = None
    if current_summary is not None:
        style, language = profile_service.get_reading_variant(profile, config)
        current = (
            article_service.get_expanded_story(current_summary["id"], style, language, config)
            or current_summary
        )

    return {
        "total": total,
        "read_count": read_count,
        "current": current,
        "completed": completed,
        "rewrites_pending": rewrites_pending,
        "profile": profile,
        "streak_incremented": False,
    }


def mark_read_and_maybe_complete(
    user_id: int,
    story_id: str,
    config: dict[str, Any],
) -> dict[str, Any]:
    """Mark a story read, then advance the streak if the digest is now complete.

    Returns the recomputed session state, plus ``streak_incremented`` (True when
    this completion actually moved the streak — i.e. it wasn't already counted
    today). The streak update is idempotent for same-day reads, so calling it on
    every completion is safe.
    """
    profile = profile_service.get_profile_with_selections(user_id)
    db_reading.mark_story_read(user_id, story_id)

    state = get_session_state(user_id, config, profile=profile)

    streak_incremented = False
    if state["completed"]:
        already_counted_today = (
            profile is not None and profile.get("last_read_date") == date.today()
        )
        update_reading_streak(user_id)
        streak_incremented = not already_counted_today
        # Refresh the profile so the completion screen shows the new streak value.
        state["profile"] = profile_service.get_profile_with_selections(user_id)

    state["streak_incremented"] = streak_incremented
    return state
