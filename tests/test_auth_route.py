"""Tests for auth routes: /login, /register, /logout."""

from unittest.mock import patch

from flask.testing import FlaskClient

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

CSRF_TOKEN = "test-csrf-token"


def _set_csrf(client: FlaskClient) -> None:
    """Inject a known CSRF token into the session so POST requests succeed."""
    with client.session_transaction() as sess:
        sess["_csrf_token"] = CSRF_TOKEN


# ---------------------------------------------------------------------------
# /login GET
# ---------------------------------------------------------------------------


def test_login_get_returns_form(client: FlaskClient) -> None:
    """GET /login renders the login page."""
    response = client.get("/login")
    assert response.status_code == 200
    assert b"<form" in response.data


def test_login_get_no_auth_required(client: FlaskClient) -> None:
    """GET /login is accessible without a session (public endpoint)."""
    response = client.get("/login")
    # Must not redirect to itself
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# /login POST
# ---------------------------------------------------------------------------


def test_login_post_missing_fields_shows_error(client: FlaskClient) -> None:
    """POST /login with empty credentials shows an error page, not a redirect."""
    _set_csrf(client)
    response = client.post("/login", data={"email": "", "password": "", "csrf_token": CSRF_TOKEN})
    assert response.status_code == 200
    assert b"required" in response.data.lower()


def test_login_post_missing_password_shows_error(client: FlaskClient) -> None:
    """POST /login with email but no password shows an error page."""
    _set_csrf(client)
    response = client.post(
        "/login", data={"email": "user@example.com", "password": "", "csrf_token": CSRF_TOKEN}
    )
    assert response.status_code == 200
    assert b"required" in response.data.lower()


def test_login_post_invalid_credentials_shows_error(client: FlaskClient) -> None:
    """POST /login with wrong credentials re-renders the form with an error."""
    _set_csrf(client)
    with patch("app.routes.auth.auth_service.authenticate_user", return_value=None):
        response = client.post(
            "/login",
            data={"email": "bad@example.com", "password": "badpass", "csrf_token": CSRF_TOKEN},
        )
    assert response.status_code == 200
    assert b"flash-error" in response.data


def test_login_post_valid_credentials_redirects_to_reader(client: FlaskClient) -> None:
    """POST /login with valid credentials redirects to the reader index."""
    _set_csrf(client)
    with (
        patch("app.routes.auth.auth_service.authenticate_user", return_value=1),
        patch("app.routes.auth.db_users.update_last_login"),
    ):
        response = client.post(
            "/login",
            data={"email": "user@example.com", "password": "correctpass", "csrf_token": CSRF_TOKEN},
            follow_redirects=False,
        )
    assert response.status_code == 302
    assert "/" in response.location


def test_login_post_sets_session(client: FlaskClient) -> None:
    """POST /login with valid credentials stores user_id in the session."""
    _set_csrf(client)
    with (
        patch("app.routes.auth.auth_service.authenticate_user", return_value=5),
        patch("app.routes.auth.db_users.update_last_login"),
    ):
        with client.session_transaction() as sess:
            assert "user_id" not in sess

        client.post(
            "/login",
            data={"email": "user@example.com", "password": "pass", "csrf_token": CSRF_TOKEN},
            follow_redirects=False,
        )

    with client.session_transaction() as sess:
        assert sess.get("user_id") == 5


def test_login_post_missing_csrf_returns_403(client: FlaskClient) -> None:
    """POST /login without a CSRF token returns 403."""
    response = client.post("/login", data={"email": "user@example.com", "password": "pass"})
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# /register GET
# ---------------------------------------------------------------------------


def test_register_get_returns_form(client: FlaskClient) -> None:
    """GET /register renders the registration page."""
    response = client.get("/register")
    assert response.status_code == 200
    assert b"<form" in response.data


# ---------------------------------------------------------------------------
# /register POST
# ---------------------------------------------------------------------------


def test_register_post_missing_fields_shows_error(client: FlaskClient) -> None:
    """POST /register with empty fields shows an error."""
    _set_csrf(client)
    response = client.post(
        "/register", data={"email": "", "password": "", "csrf_token": CSRF_TOKEN}
    )
    assert response.status_code == 200
    assert b"required" in response.data.lower()


def test_register_post_short_password_shows_error(client: FlaskClient) -> None:
    """POST /register with < 8 char password shows a password-length error."""
    _set_csrf(client)
    response = client.post(
        "/register",
        data={"email": "new@example.com", "password": "short", "csrf_token": CSRF_TOKEN},
    )
    assert response.status_code == 200
    assert b"flash-error" in response.data


def test_register_post_duplicate_email_shows_error(client: FlaskClient) -> None:
    """POST /register with a taken email shows an error."""
    _set_csrf(client)
    with patch("app.routes.auth.auth_service.register_user", side_effect=ValueError("taken")):
        response = client.post(
            "/register",
            data={
                "email": "taken@example.com",
                "password": "password123",
                "csrf_token": CSRF_TOKEN,
            },
        )
    assert response.status_code == 200
    assert b"flash-error" in response.data


def test_register_post_success_redirects_to_setup(client: FlaskClient) -> None:
    """POST /register with valid data redirects to /setup."""
    _set_csrf(client)
    with patch("app.routes.auth.auth_service.register_user", return_value=10):
        response = client.post(
            "/register",
            data={
                "email": "new@example.com",
                "password": "securepass",
                "csrf_token": CSRF_TOKEN,
            },
            follow_redirects=False,
        )
    assert response.status_code == 302
    assert "/setup" in response.location


def test_register_post_success_sets_session(client: FlaskClient) -> None:
    """POST /register stores the new user_id in the session."""
    _set_csrf(client)
    with patch("app.routes.auth.auth_service.register_user", return_value=10):
        client.post(
            "/register",
            data={
                "email": "new@example.com",
                "password": "securepass",
                "csrf_token": CSRF_TOKEN,
            },
            follow_redirects=False,
        )
    with client.session_transaction() as sess:
        assert sess.get("user_id") == 10


def test_register_post_missing_csrf_returns_403(client: FlaskClient) -> None:
    """POST /register without a CSRF token returns 403."""
    response = client.post("/register", data={"email": "new@example.com", "password": "securepass"})
    assert response.status_code == 403


# ---------------------------------------------------------------------------
# /logout POST
# ---------------------------------------------------------------------------


def test_logout_clears_session_and_redirects(client: FlaskClient) -> None:
    """POST /logout clears the session and redirects to /login."""
    with client.session_transaction() as sess:
        sess["user_id"] = 1
        sess["_csrf_token"] = CSRF_TOKEN

    response = client.post("/logout", data={"csrf_token": CSRF_TOKEN}, follow_redirects=False)
    assert response.status_code == 302
    assert "/login" in response.location

    with client.session_transaction() as sess:
        assert "user_id" not in sess


def test_logout_missing_csrf_returns_403(client: FlaskClient) -> None:
    """POST /logout without a CSRF token returns 403."""
    with client.session_transaction() as sess:
        sess["user_id"] = 1

    response = client.post("/logout", follow_redirects=False)
    assert response.status_code == 403
