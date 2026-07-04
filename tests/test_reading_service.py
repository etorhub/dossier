"""Tests for the guided-session logic in app/services/reading_service.py.

Pure unit tests: the DB and article-service layers are mocked, so no database
is required.
"""

from datetime import date, timedelta
from unittest.mock import patch

from app.services import reading_service

_PROFILE = {
    "user_id": 1,
    "reading_streak": 4,
    "longest_streak": 6,
    "last_read_date": None,
}

_CONFIG: dict = {}

_FEED = [
    {"id": "s1", "title": "One", "full_text": "a"},
    {"id": "s2", "title": "Two", "full_text": "b"},
]


def test_get_session_state_points_at_first_unread() -> None:
    """With nothing read, current is the first story and nothing is complete."""
    with (
        patch(
            "app.services.reading_service.article_service.get_feed",
            return_value=(_FEED, False),
        ),
        patch(
            "app.services.reading_service.db_reading.get_read_story_ids",
            return_value=set(),
        ),
        patch(
            "app.services.reading_service.profile_service.get_reading_variant",
            return_value=("neutral", "en"),
        ),
        patch(
            "app.services.reading_service.article_service.get_expanded_story",
            return_value=_FEED[0],
        ),
    ):
        state = reading_service.get_session_state(1, _CONFIG, profile=_PROFILE)

    assert state["total"] == 2
    assert state["read_count"] == 0
    assert state["completed"] is False
    assert state["current"]["id"] == "s1"


def test_get_session_state_completed_when_all_read() -> None:
    """When every story is read, the session is complete and there is no current."""
    with (
        patch(
            "app.services.reading_service.article_service.get_feed",
            return_value=(_FEED, False),
        ),
        patch(
            "app.services.reading_service.db_reading.get_read_story_ids",
            return_value={"s1", "s2"},
        ),
    ):
        state = reading_service.get_session_state(1, _CONFIG, profile=_PROFILE)

    assert state["completed"] is True
    assert state["current"] is None
    assert state["read_count"] == 2


def test_mark_read_advances_streak_on_completion() -> None:
    """Finishing the digest triggers the streak update and flags the increment."""
    with (
        patch(
            "app.services.reading_service.profile_service.get_profile_with_selections",
            return_value=_PROFILE,
        ),
        patch("app.services.reading_service.db_reading.mark_story_read") as mock_mark,
        patch(
            "app.services.reading_service.article_service.get_feed",
            return_value=(_FEED, False),
        ),
        patch(
            "app.services.reading_service.db_reading.get_read_story_ids",
            return_value={"s1", "s2"},
        ),
        patch("app.services.reading_service.update_reading_streak") as mock_streak,
    ):
        state = reading_service.mark_read_and_maybe_complete(1, "s2", _CONFIG)

    mock_mark.assert_called_once_with(1, "s2")
    mock_streak.assert_called_once_with(1)
    assert state["completed"] is True
    assert state["streak_incremented"] is True


def test_mark_read_no_streak_when_incomplete() -> None:
    """Reading a story mid-digest does not move the streak."""
    with (
        patch(
            "app.services.reading_service.profile_service.get_profile_with_selections",
            return_value=_PROFILE,
        ),
        patch("app.services.reading_service.db_reading.mark_story_read"),
        patch(
            "app.services.reading_service.article_service.get_feed",
            return_value=(_FEED, False),
        ),
        patch(
            "app.services.reading_service.db_reading.get_read_story_ids",
            return_value={"s1"},
        ),
        patch(
            "app.services.reading_service.profile_service.get_reading_variant",
            return_value=("neutral", "en"),
        ),
        patch(
            "app.services.reading_service.article_service.get_expanded_story",
            return_value=_FEED[1],
        ),
        patch("app.services.reading_service.update_reading_streak") as mock_streak,
    ):
        state = reading_service.mark_read_and_maybe_complete(1, "s1", _CONFIG)

    mock_streak.assert_not_called()
    assert state["completed"] is False
    assert state["streak_incremented"] is False


def test_mark_read_streak_not_flagged_when_already_counted_today() -> None:
    """Re-completing after today's streak was already counted does not re-flag it."""
    profile_today = {**_PROFILE, "last_read_date": date.today()}
    with (
        patch(
            "app.services.reading_service.profile_service.get_profile_with_selections",
            return_value=profile_today,
        ),
        patch("app.services.reading_service.db_reading.mark_story_read"),
        patch(
            "app.services.reading_service.article_service.get_feed",
            return_value=(_FEED, False),
        ),
        patch(
            "app.services.reading_service.db_reading.get_read_story_ids",
            return_value={"s1", "s2"},
        ),
        patch("app.services.reading_service.update_reading_streak") as mock_streak,
    ):
        state = reading_service.mark_read_and_maybe_complete(1, "s2", _CONFIG)

    # Still called (idempotent no-op in SQL), but not flagged as a fresh increment.
    mock_streak.assert_called_once_with(1)
    assert state["streak_incremented"] is False


def test_get_session_state_yesterday_profile_is_untouched() -> None:
    """A profile last read yesterday still yields a normal (incomplete) session."""
    profile_yesterday = {**_PROFILE, "last_read_date": date.today() - timedelta(days=1)}
    with (
        patch(
            "app.services.reading_service.article_service.get_feed",
            return_value=(_FEED, False),
        ),
        patch(
            "app.services.reading_service.db_reading.get_read_story_ids",
            return_value=set(),
        ),
        patch(
            "app.services.reading_service.profile_service.get_reading_variant",
            return_value=("neutral", "en"),
        ),
        patch(
            "app.services.reading_service.article_service.get_expanded_story",
            return_value=_FEED[0],
        ),
    ):
        state = reading_service.get_session_state(1, _CONFIG, profile=profile_yesterday)

    assert state["completed"] is False
    assert state["current"]["id"] == "s1"
