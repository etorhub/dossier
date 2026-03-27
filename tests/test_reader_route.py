"""Tests for reader routes: /, /feed, /stories/<id>/expand|collapse, /article/<id>."""

from unittest.mock import patch

from flask.testing import FlaskClient

_PROFILE = {
    "user_id": 1,
    "language": "en",
    "preferred_style": "neutral",
    "high_contrast": False,
    "topic_ids": ["general", "technology"],
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


def _auth(client: FlaskClient) -> None:
    """Put user_id=1 in the session."""
    with client.session_transaction() as sess:
        sess["user_id"] = 1


# ---------------------------------------------------------------------------
# GET / — index
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


def test_index_renders_feed_for_authenticated_user(client: FlaskClient) -> None:
    """GET / renders the index page for a logged-in user with a profile."""
    _auth(client)
    with (
        patch(
            "app.routes.reader.profile_service.get_profile_with_selections",
            return_value=_PROFILE,
        ),
        patch("app.routes.reader.load_config", return_value=_CONFIG),
        patch("app.routes.reader.article_service.get_feed", return_value=([], False)),
        patch("app.db.users.get_user_by_id", return_value={"is_admin": False, "email": "u@e.com"}),
        patch("app.services.profile_service.get_profile_with_selections", return_value=_PROFILE),
    ):
        response = client.get("/")
    assert response.status_code == 200


def test_index_topic_filter_ignored_when_not_in_profile(client: FlaskClient) -> None:
    """GET /?topic=unknown ignores the filter when not in the user's topic list."""
    _auth(client)
    with (
        patch(
            "app.routes.reader.profile_service.get_profile_with_selections",
            return_value=_PROFILE,
        ),
        patch("app.routes.reader.load_config", return_value=_CONFIG),
        patch("app.routes.reader.article_service.get_feed", return_value=([], False)) as mock_feed,
        patch("app.db.users.get_user_by_id", return_value={"is_admin": False, "email": "u@e.com"}),
        patch("app.services.profile_service.get_profile_with_selections", return_value=_PROFILE),
    ):
        client.get("/?topic=nonexistent_topic")
    # topic_filter should have been cleared to None
    _call_kwargs = mock_feed.call_args
    assert _call_kwargs.kwargs.get("topic_filter") is None


def test_index_topic_filter_applied_when_valid(client: FlaskClient) -> None:
    """GET /?topic=general passes the filter through when it is in the profile."""
    _auth(client)
    with (
        patch(
            "app.routes.reader.profile_service.get_profile_with_selections",
            return_value=_PROFILE,
        ),
        patch("app.routes.reader.load_config", return_value=_CONFIG),
        patch("app.routes.reader.article_service.get_feed", return_value=([], False)) as mock_feed,
        patch("app.db.users.get_user_by_id", return_value={"is_admin": False, "email": "u@e.com"}),
        patch("app.services.profile_service.get_profile_with_selections", return_value=_PROFILE),
    ):
        client.get("/?topic=general")
    _call_kwargs = mock_feed.call_args
    assert _call_kwargs.kwargs.get("topic_filter") == "general"


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
        patch("app.db.users.get_user_by_id", return_value={"is_admin": False, "email": "u@e.com"}),
        patch("app.services.profile_service.get_profile_with_selections", return_value=_PROFILE),
    ):
        response = client.get("/feed")
    assert response.status_code == 200


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
    assert b"encontrado" in response.data.lower()


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
    assert b"encontrado" in response.data.lower()


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
