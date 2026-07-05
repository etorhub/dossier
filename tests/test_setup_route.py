"""Tests for setup wizard route: GET /setup/ and POST /setup/."""

from unittest.mock import patch

from flask.testing import FlaskClient

_SOURCES = [
    {"id": "src1", "name": "Source 1", "topics": ["general", "technology"]},
    {"id": "src2", "name": "Source 2", "topics": ["technology", "sports"]},
]

_CONFIG = {
    "rewriting": {
        "languages": [
            {"id": "ca", "label": "Catalan"},
            {"id": "es", "label": "Spanish"},
            {"id": "en", "label": "English"},
        ]
    },
    "topics": {
        "general": {"label": "General", "icon": "📰", "emoji": "📰"},
        "technology": {"label": "Technology", "icon": "💻", "emoji": "💻"},
        "sports": {"label": "Sports", "icon": "⚽", "emoji": "⚽"},
    },
}

_STYLE_OPTIONS = [{"id": "neutral", "label": "Neutral"}]


def _auth(client: FlaskClient) -> None:
    with client.session_transaction() as sess:
        sess["user_id"] = 1


# ---------------------------------------------------------------------------
# GET /setup/
# ---------------------------------------------------------------------------


def test_setup_get_redirects_to_login_when_unauthenticated(client: FlaskClient) -> None:
    """GET /setup/ redirects to /login without a session."""
    response = client.get("/setup/", follow_redirects=False)
    assert response.status_code == 302
    assert "/login" in response.location


def test_setup_get_renders_form_for_authenticated_user(client: FlaskClient) -> None:
    """GET /setup/ renders the setup form for a logged-in user."""
    _auth(client)
    with (
        patch("app.routes.setup.load_sources", return_value=_SOURCES),
        patch("app.routes.setup.load_config", return_value=_CONFIG),
        patch(
            "app.routes.setup.profile_service.get_style_options",
            return_value=_STYLE_OPTIONS,
        ),
        patch("app.db.users.get_user_by_id", return_value={"is_admin": False, "email": "u@e.com"}),
        patch("app.services.profile_service.get_profile_with_selections", return_value=None),
    ):
        response = client.get("/setup/")
    assert response.status_code == 200
    assert b"<form" in response.data
    assert b'name="language"' not in response.data


# ---------------------------------------------------------------------------
# POST /setup/
# ---------------------------------------------------------------------------


def test_setup_post_redirects_to_login_when_unauthenticated(client: FlaskClient) -> None:
    """POST /setup/ redirects to /login without a session."""
    response = client.post("/setup/", data={}, follow_redirects=False)
    assert response.status_code == 302
    assert "/login" in response.location


def test_setup_post_saves_and_redirects_to_reader(client: FlaskClient) -> None:
    """POST /setup/ with valid data saves the profile and redirects to /."""
    _auth(client)
    with (
        patch("app.routes.setup.load_sources", return_value=_SOURCES),
        patch("app.routes.setup.load_config", return_value=_CONFIG),
        patch("app.routes.setup.profile_service.normalize_preferred_style", return_value="neutral"),
        patch("app.routes.setup.profile_service.save_setup") as mock_save,
        patch("app.db.users.get_user_by_id", return_value={"is_admin": False, "email": "u@e.com"}),
        patch("app.services.profile_service.get_profile_with_selections", return_value=None),
    ):
        response = client.post(
            "/setup/",
            data={
                "location": "Barcelona",
                "preferred_style": "neutral",
                "topics": ["general", "technology"],
            },
            follow_redirects=False,
        )

    assert response.status_code == 302
    assert response.location == "/"
    mock_save.assert_called_once()


def test_setup_post_uses_all_topics_when_none_selected(client: FlaskClient) -> None:
    """POST /setup/ with no topics selected defaults to all available topics."""
    _auth(client)
    with (
        patch("app.routes.setup.load_sources", return_value=_SOURCES),
        patch("app.routes.setup.load_config", return_value=_CONFIG),
        patch("app.routes.setup.profile_service.normalize_preferred_style", return_value="neutral"),
        patch("app.routes.setup.profile_service.save_setup") as mock_save,
        patch("app.db.users.get_user_by_id", return_value={"is_admin": False, "email": "u@e.com"}),
        patch("app.services.profile_service.get_profile_with_selections", return_value=None),
    ):
        client.post(
            "/setup/",
            data={"location": "", "preferred_style": "neutral"},
            follow_redirects=False,
        )

    _, _, call_topic_ids = mock_save.call_args.args
    # Should include all unique topics from sources (sorted)
    assert sorted(call_topic_ids) == ["general", "sports", "technology"]


def test_setup_post_passes_high_contrast_flag(client: FlaskClient) -> None:
    """POST /setup/ with high_contrast=on passes high_contrast=True to save_setup."""
    _auth(client)
    with (
        patch("app.routes.setup.load_sources", return_value=_SOURCES),
        patch("app.routes.setup.load_config", return_value=_CONFIG),
        patch("app.routes.setup.profile_service.normalize_preferred_style", return_value="neutral"),
        patch("app.routes.setup.profile_service.save_setup") as mock_save,
        patch("app.db.users.get_user_by_id", return_value={"is_admin": False, "email": "u@e.com"}),
        patch("app.services.profile_service.get_profile_with_selections", return_value=None),
    ):
        client.post(
            "/setup/",
            data={
                "preferred_style": "neutral",
                "high_contrast": "on",
                "topics": ["general"],
            },
            follow_redirects=False,
        )

    form_data = mock_save.call_args.args[1]
    assert form_data["high_contrast"] is True


def test_setup_post_location_is_none_when_blank(client: FlaskClient) -> None:
    """POST /setup/ with a blank location stores None (not an empty string)."""
    _auth(client)
    with (
        patch("app.routes.setup.load_sources", return_value=_SOURCES),
        patch("app.routes.setup.load_config", return_value=_CONFIG),
        patch("app.routes.setup.profile_service.normalize_preferred_style", return_value="neutral"),
        patch("app.routes.setup.profile_service.save_setup") as mock_save,
        patch("app.db.users.get_user_by_id", return_value={"is_admin": False, "email": "u@e.com"}),
        patch("app.services.profile_service.get_profile_with_selections", return_value=None),
    ):
        client.post(
            "/setup/",
            data={"location": "   ", "preferred_style": "neutral"},
            follow_redirects=False,
        )

    form_data = mock_save.call_args.args[1]
    assert form_data["location"] is None


# ---------------------------------------------------------------------------
# _all_topics helper (indirectly tested via the route above, but explicit here)
# ---------------------------------------------------------------------------


def test_all_topics_deduplicates_and_sorts() -> None:
    """_all_topics returns unique topic ids in sorted order."""
    from app.routes.setup import _all_topics

    sources = [
        {"topics": ["b", "a"]},
        {"topics": ["a", "c"]},
        {"topics": []},
    ]
    result = _all_topics(sources)
    assert result == ["a", "b", "c"]
