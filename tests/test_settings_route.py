"""Tests for settings route."""

from unittest.mock import patch

import pytest
from flask.testing import FlaskClient


@pytest.fixture
def mock_sources() -> list[dict]:
    """Minimal sources list for settings form."""
    return [
        {"id": "s1", "name": "Source 1", "topics": ["general"]},
        {"id": "s2", "name": "Source 2", "topics": ["general"]},
    ]


@pytest.fixture
def mock_profile() -> dict:
    """Profile with all regeneration-affecting fields."""
    return {
        "user_id": 1,
        "location": "Barcelona",
        "language": "ca",
        "preferred_style": "neutral",
        "high_contrast": False,
        "topic_ids": ["general"],
    }


def test_settings_post_only_high_contrast_saves_without_confirmation(
    client: FlaskClient,
    mock_sources: list[dict],
    mock_profile: dict,
) -> None:
    """When only high_contrast changes, save proceeds without regeneration confirmation."""
    with (
        patch("app.routes.settings.load_sources", return_value=mock_sources),
        patch(
            "app.routes.settings.profile_service.get_profile_with_selections",
            return_value=mock_profile,
        ),
        patch(
            "app.routes.settings.profile_service.regeneration_needed",
            return_value=False,
        ),
        patch("app.routes.settings.profile_service.save_setup"),
        patch("app.db.users.get_user_by_id", return_value={"is_admin": False, "email": "t@t.com"}),
        patch("app.db.users.get_profile", return_value=mock_profile),
    ):
        with client.session_transaction() as sess:
            sess["user_id"] = 1

        response = client.post(
            "/settings/",
            data={
                "location": "Barcelona",
                "language": "ca",
                "preferred_style": "neutral",
                "high_contrast": "on",
                "topics": ["general"],
            },
            follow_redirects=False,
        )

        assert response.status_code == 302
        assert "saved=1" in response.location


def test_settings_post_regeneration_field_saves_when_confirmed(
    client: FlaskClient,
    mock_sources: list[dict],
    mock_profile: dict,
) -> None:
    """When a regeneration-affecting field changes and user confirms, save proceeds."""
    with (
        patch("app.routes.settings.load_sources", return_value=mock_sources),
        patch(
            "app.routes.settings.profile_service.get_profile_with_selections",
            return_value=mock_profile,
        ),
        patch(
            "app.routes.settings.profile_service.regeneration_needed",
            return_value=True,
        ),
        patch("app.routes.settings.profile_service.save_setup"),
        patch("app.db.users.get_user_by_id", return_value={"is_admin": False, "email": "t@t.com"}),
        patch("app.db.users.get_profile", return_value=mock_profile),
    ):
        with client.session_transaction() as sess:
            sess["user_id"] = 1

        response = client.post(
            "/settings/",
            data={
                "location": "Barcelona",
                "language": "es",
                "preferred_style": "neutral",
                "confirm_regenerate": "1",
                "topics": ["general"],
            },
            follow_redirects=False,
        )

        assert response.status_code == 302
        assert "saved=1" in response.location


def test_settings_post_regeneration_needed_shows_confirmation(
    client: FlaskClient,
    mock_sources: list[dict],
    mock_profile: dict,
) -> None:
    """When regeneration needed without confirm, shows confirmation block."""
    with (
        patch("app.routes.settings.load_sources", return_value=mock_sources),
        patch(
            "app.routes.settings.profile_service.get_profile_with_selections",
            return_value=mock_profile,
        ),
        patch(
            "app.routes.settings.profile_service.regeneration_needed",
            return_value=True,
        ),
        patch("app.routes.settings.profile_service.save_setup"),
        patch("app.db.users.get_user_by_id", return_value={"is_admin": False, "email": "t@t.com"}),
        patch("app.db.users.get_profile", return_value=mock_profile),
    ):
        with client.session_transaction() as sess:
            sess["user_id"] = 1

        response = client.post(
            "/settings/",
            data={
                "location": "Barcelona",
                "language": "es",
                "preferred_style": "neutral",
                "topics": ["general"],
            },
            follow_redirects=False,
        )

        assert response.status_code == 200
        assert b'role="alert"' in response.data
        assert b'name="confirm_regenerate"' in response.data
