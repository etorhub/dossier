"""Tests for reader routes: session (/), /read/advance, /review, /feed, /stats,
/stories/<id>/expand|collapse, /article/<id>."""

from unittest.mock import patch

from flask.testing import FlaskClient

_PROFILE = {
    "user_id": 1,
    "language": "en",
    "preferred_style": "neutral",
    "high_contrast": False,
    "topic_ids": ["general", "technology"],
    "reading_streak": 3,
    "longest_streak": 5,
    "last_read_date": None,
}

_CONFIG = {
    "topics": {
        "general": {"label": "General", "icon": "📰", "emoji": "📰"},
        "technology": {"label": "Technology", "icon": "💻", "emoji": "💻"},
    }
}

_STORY = {
    "id": "story-uuid-1",
    "title": "Test headline",
    "summary": "Short summary.",
    "full_text": "Long article text.",
    "sources": [],
}

_STEP_STATE = {
    "total": 2,
    "read_count": 0,
    "current": _STORY,
    "completed": False,
    "rewrites_pending": False,
    "profile": _PROFILE,
    "streak_incremented": False,
}

_COMPLETE_STATE = {
    "total": 2,
    "read_count": 2,
    "current": None,
    "completed": True,
    "rewrites_pending": False,
    "profile": _PROFILE,
    "streak_incremented": True,
}


def _auth(client: FlaskClient) -> None:
    """Put user_id=1 in the session."""
    with client.session_transaction() as sess:
        sess["user_id"] = 1


# ---------------------------------------------------------------------------
# GET / — guided session
# ---------------------------------------------------------------------------


def test_index_redirects_to_login_when_unauthenticated(client: FlaskClient) -> None:
    """GET / redirects to /login when there is no session."""
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 302
    assert "/login" in response.location


def test_index_redirects_to_setup_when_no_profile(client: FlaskClient) -> None:
    """GET / redirects to /setup when the user has no profile yet."""
    _auth(client)
    with (
        patch("app.routes.reader.profile_service.get_profile_with_selections", return_value=None),
        patch("app.db.users.get_user_by_id", return_value={"is_admin": False, "email": "u@e.com"}),
        patch("app.services.profile_service.get_profile_with_selections", return_value=None),
    ):
        response = client.get("/", follow_redirects=False)
    assert response.status_code == 302
    assert "/setup" in response.location


def test_index_renders_session_for_authenticated_user(client: FlaskClient) -> None:
    """GET / renders the guided session for a logged-in user with a profile."""
    _auth(client)
    with (
        patch(
            "app.routes.reader.profile_service.get_profile_with_selections",
            return_value=_PROFILE,
        ),
        patch("app.routes.reader.reading_service.get_session_state", return_value=_STEP_STATE),
        patch("app.db.users.get_user_by_id", return_value={"is_admin": False, "email": "u@e.com"}),
        patch("app.services.profile_service.get_profile_with_selections", return_value=_PROFILE),
    ):
        response = client.get("/")
    assert response.status_code == 200
    assert b"Test headline" in response.data


# ---------------------------------------------------------------------------
# POST /read/advance
# ---------------------------------------------------------------------------


def test_advance_redirects_when_unauthenticated(client: FlaskClient) -> None:
    """POST /read/advance redirects to /login without a session."""
    response = client.post("/read/advance", data={}, follow_redirects=False)
    assert response.status_code == 302
    assert "/login" in response.location


def test_advance_returns_next_step_partial(client: FlaskClient) -> None:
    """POST /read/advance (HTMX) marks read and returns the next step."""
    _auth(client)
    with (
        patch(
            "app.routes.reader.profile_service.get_profile_with_selections",
            return_value=_PROFILE,
        ),
        patch("app.routes.reader.validate_csrf_token", return_value=True),
        patch("app.routes.reader.load_config", return_value=_CONFIG),
        patch(
            "app.routes.reader.reading_service.mark_read_and_maybe_complete",
            return_value=_STEP_STATE,
        ) as mock_mark,
        patch("app.db.users.get_user_by_id", return_value={"is_admin": False, "email": "u@e.com"}),
        patch("app.services.profile_service.get_profile_with_selections", return_value=_PROFILE),
    ):
        response = client.post(
            "/read/advance",
            data={"story_id": "story-uuid-1", "csrf_token": "x"},
            headers={"HX-Request": "true"},
        )
    assert response.status_code == 200
    assert b"Test headline" in response.data
    mock_mark.assert_called_once_with(1, "story-uuid-1", _CONFIG)


def test_advance_returns_completion_partial_on_finish(client: FlaskClient) -> None:
    """POST /read/advance (HTMX) returns the completion screen when the digest is done."""
    _auth(client)
    with (
        patch(
            "app.routes.reader.profile_service.get_profile_with_selections",
            return_value=_PROFILE,
        ),
        patch("app.routes.reader.validate_csrf_token", return_value=True),
        patch(
            "app.routes.reader.reading_service.mark_read_and_maybe_complete",
            return_value=_COMPLETE_STATE,
        ),
        patch("app.db.users.get_user_by_id", return_value={"is_admin": False, "email": "u@e.com"}),
        patch("app.services.profile_service.get_profile_with_selections", return_value=_PROFILE),
    ):
        response = client.post(
            "/read/advance",
            data={"story_id": "story-uuid-2", "csrf_token": "x"},
            headers={"HX-Request": "true"},
        )
    assert response.status_code == 200
    # Completion screen text (translated); "+1" appears when the streak advanced.
    assert b"+1" in response.data


def test_advance_without_htmx_redirects_to_index(client: FlaskClient) -> None:
    """POST /read/advance without HX-Request falls back to a full-page redirect."""
    _auth(client)
    with (
        patch(
            "app.routes.reader.profile_service.get_profile_with_selections",
            return_value=_PROFILE,
        ),
        patch("app.routes.reader.validate_csrf_token", return_value=True),
        patch(
            "app.routes.reader.reading_service.mark_read_and_maybe_complete",
            return_value=_STEP_STATE,
        ),
        patch("app.db.users.get_user_by_id", return_value={"is_admin": False, "email": "u@e.com"}),
        patch("app.services.profile_service.get_profile_with_selections", return_value=_PROFILE),
    ):
        response = client.post(
            "/read/advance",
            data={"story_id": "story-uuid-1", "csrf_token": "x"},
            follow_redirects=False,
        )
    assert response.status_code == 302
    assert response.location.endswith("/")


def test_advance_invalid_csrf_redirects(client: FlaskClient) -> None:
    """POST /read/advance with a bad CSRF token redirects without mutating state."""
    _auth(client)
    with (
        patch("app.routes.reader.validate_csrf_token", return_value=False),
        patch("app.routes.reader.reading_service.mark_read_and_maybe_complete") as mock_mark,
        patch("app.db.users.get_user_by_id", return_value={"is_admin": False, "email": "u@e.com"}),
        patch("app.services.profile_service.get_profile_with_selections", return_value=_PROFILE),
    ):
        response = client.post(
            "/read/advance",
            data={"story_id": "story-uuid-1", "csrf_token": "bad"},
            headers={"HX-Request": "true"},
            follow_redirects=False,
        )
    assert response.status_code == 302
    mock_mark.assert_not_called()


# ---------------------------------------------------------------------------
# GET /review — scrollable feed
# ---------------------------------------------------------------------------


def test_review_renders_feed_for_authenticated_user(client: FlaskClient) -> None:
    """GET /review renders the review feed."""
    _auth(client)
    with (
        patch(
            "app.routes.reader.profile_service.get_profile_with_selections",
            return_value=_PROFILE,
        ),
        patch("app.routes.reader.article_service.get_feed", return_value=([], False)),
        patch("app.routes.reader.db_reading.get_read_story_ids", return_value=set()),
        patch("app.db.users.get_user_by_id", return_value={"is_admin": False, "email": "u@e.com"}),
        patch("app.services.profile_service.get_profile_with_selections", return_value=_PROFILE),
    ):
        response = client.get("/review")
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# GET /feed — HTMX partial
# ---------------------------------------------------------------------------


def test_feed_partial_redirects_when_unauthenticated(client: FlaskClient) -> None:
    """GET /feed redirects to /login without a session."""
    response = client.get("/feed", follow_redirects=False)
    assert response.status_code == 302
    assert "/login" in response.location


def test_feed_partial_renders_for_authenticated_user(client: FlaskClient) -> None:
    """GET /feed returns the feed_content partial."""
    _auth(client)
    with (
        patch(
            "app.routes.reader.profile_service.get_profile_with_selections",
            return_value=_PROFILE,
        ),
        patch("app.routes.reader.article_service.get_feed", return_value=([], False)),
        patch("app.routes.reader.db_reading.get_read_story_ids", return_value=set()),
        patch("app.db.users.get_user_by_id", return_value={"is_admin": False, "email": "u@e.com"}),
        patch("app.services.profile_service.get_profile_with_selections", return_value=_PROFILE),
    ):
        response = client.get("/feed")
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# GET /stats
# ---------------------------------------------------------------------------


def test_stats_renders_streak_numbers(client: FlaskClient) -> None:
    """GET /stats renders the current and longest streak values."""
    _auth(client)
    with (
        patch(
            "app.routes.reader.profile_service.get_profile_with_selections",
            return_value=_PROFILE,
        ),
        patch("app.routes.reader.reading_service.get_session_state", return_value=_STEP_STATE),
        patch("app.db.users.get_user_by_id", return_value={"is_admin": False, "email": "u@e.com"}),
        patch("app.services.profile_service.get_profile_with_selections", return_value=_PROFILE),
    ):
        response = client.get("/stats")
    assert response.status_code == 200
    assert b"3" in response.data  # current streak
    assert b"5" in response.data  # longest streak


# ---------------------------------------------------------------------------
# GET /stories/<id>/expand
# ---------------------------------------------------------------------------


def test_expand_story_redirects_when_unauthenticated(client: FlaskClient) -> None:
    """GET /stories/<id>/expand redirects to login without a session."""
    response = client.get("/stories/abc/expand", follow_redirects=False)
    assert response.status_code == 302
    assert "/login" in response.location


def test_expand_story_renders_expanded_article(client: FlaskClient) -> None:
    """GET /stories/<id>/expand returns the expanded article partial."""
    _auth(client)
    with (
        patch(
            "app.routes.reader.profile_service.get_profile_with_selections",
            return_value=_PROFILE,
        ),
        patch("app.routes.reader.load_config", return_value=_CONFIG),
        patch(
            "app.routes.reader.profile_service.get_reading_variant",
            return_value=("neutral", "en"),
        ),
        patch(
            "app.routes.reader.article_service.get_expanded_story",
            return_value=_STORY,
        ),
        patch("app.routes.reader.reading_service.mark_read_and_maybe_complete"),
        patch("app.db.users.get_user_by_id", return_value={"is_admin": False, "email": "u@e.com"}),
        patch("app.services.profile_service.get_profile_with_selections", return_value=_PROFILE),
    ):
        response = client.get("/stories/story-uuid-1/expand")
    assert response.status_code == 200


def test_expand_story_shows_not_found_when_story_missing(client: FlaskClient) -> None:
    """GET /stories/<id>/expand shows an error when the story does not exist."""
    _auth(client)
    with (
        patch(
            "app.routes.reader.profile_service.get_profile_with_selections",
            return_value=_PROFILE,
        ),
        patch("app.routes.reader.load_config", return_value=_CONFIG),
        patch(
            "app.routes.reader.profile_service.get_reading_variant",
            return_value=("neutral", "en"),
        ),
        patch("app.routes.reader.article_service.get_expanded_story", return_value=None),
        patch("app.db.users.get_user_by_id", return_value={"is_admin": False, "email": "u@e.com"}),
        patch("app.services.profile_service.get_profile_with_selections", return_value=_PROFILE),
    ):
        response = client.get("/stories/nonexistent/expand")
    assert response.status_code == 200
    assert b"trobat" in response.data.lower()


# ---------------------------------------------------------------------------
# GET /stories/<id>/collapse
# ---------------------------------------------------------------------------


def test_collapse_story_renders_card(client: FlaskClient) -> None:
    """GET /stories/<id>/collapse returns the card partial."""
    _auth(client)
    with (
        patch(
            "app.routes.reader.profile_service.get_profile_with_selections",
            return_value=_PROFILE,
        ),
        patch("app.routes.reader.load_config", return_value=_CONFIG),
        patch(
            "app.routes.reader.profile_service.get_reading_variant",
            return_value=("neutral", "en"),
        ),
        patch(
            "app.routes.reader.article_service.get_expanded_story",
            return_value=_STORY,
        ),
        patch("app.db.users.get_user_by_id", return_value={"is_admin": False, "email": "u@e.com"}),
        patch("app.services.profile_service.get_profile_with_selections", return_value=_PROFILE),
    ):
        response = client.get("/stories/story-uuid-1/collapse")
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# GET /article/<id> — full page
# ---------------------------------------------------------------------------


def test_article_page_redirects_when_unauthenticated(client: FlaskClient) -> None:
    """GET /article/<id> redirects to login without a session."""
    response = client.get("/article/abc", follow_redirects=False)
    assert response.status_code == 302
    assert "/login" in response.location


def test_article_page_renders_story(client: FlaskClient) -> None:
    """GET /article/<id> renders the full article page."""
    _auth(client)
    with (
        patch(
            "app.routes.reader.profile_service.get_profile_with_selections",
            return_value=_PROFILE,
        ),
        patch("app.routes.reader.load_config", return_value=_CONFIG),
        patch(
            "app.routes.reader.profile_service.get_reading_variant",
            return_value=("neutral", "en"),
        ),
        patch(
            "app.routes.reader.article_service.get_expanded_story",
            return_value=_STORY,
        ),
        patch("app.routes.reader.reading_service.mark_read_and_maybe_complete"),
        patch("app.db.users.get_user_by_id", return_value={"is_admin": False, "email": "u@e.com"}),
        patch("app.services.profile_service.get_profile_with_selections", return_value=_PROFILE),
    ):
        response = client.get("/article/story-uuid-1")
    assert response.status_code == 200


def test_article_page_shows_not_found_when_missing(client: FlaskClient) -> None:
    """GET /article/<id> shows an error when the story does not exist."""
    _auth(client)
    with (
        patch(
            "app.routes.reader.profile_service.get_profile_with_selections",
            return_value=_PROFILE,
        ),
        patch("app.routes.reader.load_config", return_value=_CONFIG),
        patch(
            "app.routes.reader.profile_service.get_reading_variant",
            return_value=("neutral", "en"),
        ),
        patch("app.routes.reader.article_service.get_expanded_story", return_value=None),
        patch("app.db.users.get_user_by_id", return_value={"is_admin": False, "email": "u@e.com"}),
        patch("app.services.profile_service.get_profile_with_selections", return_value=_PROFILE),
    ):
        response = client.get("/article/missing")
    assert response.status_code == 200
    assert b"trobat" in response.data.lower()


# ---------------------------------------------------------------------------
# Legacy cluster redirects
# ---------------------------------------------------------------------------


def test_redirect_expand_cluster_returns_301(client: FlaskClient) -> None:
    """GET /clusters/<id>/expand issues a 301 to the new story URL."""
    _auth(client)
    response = client.get("/clusters/abc123/expand", follow_redirects=False)
    assert response.status_code == 301
    assert "/stories/abc123/expand" in response.location


def test_redirect_collapse_cluster_returns_301(client: FlaskClient) -> None:
    """GET /clusters/<id>/collapse issues a 301 to the new story URL."""
    _auth(client)
    response = client.get("/clusters/abc123/collapse", follow_redirects=False)
    assert response.status_code == 301
    assert "/stories/abc123/collapse" in response.location


# ---------------------------------------------------------------------------
# Reading state — route-level trigger tests (streak now moves on completion)
# ---------------------------------------------------------------------------


def test_expand_story_marks_read(client: FlaskClient) -> None:
    """GET /stories/<id>/expand records the read via reading_service when story exists."""
    _auth(client)
    with (
        patch(
            "app.routes.reader.profile_service.get_profile_with_selections",
            return_value=_PROFILE,
        ),
        patch("app.routes.reader.load_config", return_value=_CONFIG),
        patch(
            "app.routes.reader.profile_service.get_reading_variant",
            return_value=("neutral", "en"),
        ),
        patch(
            "app.routes.reader.article_service.get_expanded_story",
            return_value=_STORY,
        ),
        patch("app.routes.reader.reading_service.mark_read_and_maybe_complete") as mock_mark,
        patch("app.db.users.get_user_by_id", return_value={"is_admin": False, "email": "u@e.com"}),
        patch("app.services.profile_service.get_profile_with_selections", return_value=_PROFILE),
    ):
        client.get("/stories/story-uuid-1/expand")
    mock_mark.assert_called_once_with(1, "story-uuid-1", _CONFIG)


def test_article_page_marks_read(client: FlaskClient) -> None:
    """GET /article/<id> records the read via reading_service when story exists."""
    _auth(client)
    with (
        patch(
            "app.routes.reader.profile_service.get_profile_with_selections",
            return_value=_PROFILE,
        ),
        patch("app.routes.reader.load_config", return_value=_CONFIG),
        patch(
            "app.routes.reader.profile_service.get_reading_variant",
            return_value=("neutral", "en"),
        ),
        patch(
            "app.routes.reader.article_service.get_expanded_story",
            return_value=_STORY,
        ),
        patch("app.routes.reader.reading_service.mark_read_and_maybe_complete") as mock_mark,
        patch("app.db.users.get_user_by_id", return_value={"is_admin": False, "email": "u@e.com"}),
        patch("app.services.profile_service.get_profile_with_selections", return_value=_PROFILE),
    ):
        client.get("/article/story-uuid-1")
    mock_mark.assert_called_once_with(1, "story-uuid-1", _CONFIG)


def test_missing_story_does_not_mark_read(client: FlaskClient) -> None:
    """GET /stories/<id>/expand does not record a read when the story is missing."""
    _auth(client)
    with (
        patch(
            "app.routes.reader.profile_service.get_profile_with_selections",
            return_value=_PROFILE,
        ),
        patch("app.routes.reader.load_config", return_value=_CONFIG),
        patch(
            "app.routes.reader.profile_service.get_reading_variant",
            return_value=("neutral", "en"),
        ),
        patch("app.routes.reader.article_service.get_expanded_story", return_value=None),
        patch("app.routes.reader.reading_service.mark_read_and_maybe_complete") as mock_mark,
        patch("app.db.users.get_user_by_id", return_value={"is_admin": False, "email": "u@e.com"}),
        patch("app.services.profile_service.get_profile_with_selections", return_value=_PROFILE),
    ):
        client.get("/stories/nonexistent/expand")
    mock_mark.assert_not_called()
