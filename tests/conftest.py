"""Pytest fixtures."""

from collections.abc import Generator
from unittest.mock import patch

import pytest
from flask import Flask
from flask.testing import FlaskClient

from app import create_app


@pytest.fixture
def app() -> Flask:
    """Create application for testing."""
    return create_app()


@pytest.fixture
def client(app: Flask) -> FlaskClient:
    """Create test client."""
    return app.test_client()


@pytest.fixture(autouse=True)
def mock_db_context_processors(request: pytest.FixtureRequest) -> Generator[None, None, None]:
    """Mock DB calls fired by context processors on every authenticated request.

    get_locale() queries db_users.get_profile and inject_admin_flag queries
    get_user_by_id + get_profile_with_selections. Without a live database these
    raise OperationalError and turn every request into a 500. Tests that need
    specific return values can layer their own patches on top.

    Skipped for test_db_* files that exercise the DB layer directly.
    """
    if request.fspath.basename.startswith("test_db_"):
        yield
        return
    with (
        patch("app.db.users.get_profile", return_value=None),
        patch("app.db.users.get_user_by_id", return_value=None),
        patch(
            "app.services.profile_service.get_profile_with_selections",
            return_value=None,
        ),
    ):
        yield
