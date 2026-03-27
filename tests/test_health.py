"""Health check and root route smoke tests."""

from flask import Flask
from flask.testing import FlaskClient


def test_root_redirects_to_login_when_unauthenticated(client: FlaskClient) -> None:
    """GET / redirects to login when not logged in."""
    response = client.get("/")
    assert response.status_code == 302
    assert "/login" in response.location


def test_favicon_returns_204(client: FlaskClient) -> None:
    """GET /favicon.ico returns 204."""
    response = client.get("/favicon.ico")
    assert response.status_code == 204


def test_health_returns_200(client: FlaskClient) -> None:
    """GET /health returns 200."""
    response = client.get("/health")
    assert response.status_code == 200


def test_health_returns_html(client: FlaskClient) -> None:
    """GET /health returns HTML content."""
    response = client.get("/health")
    assert "html" in response.content_type
    assert b"ok" in response.data


def test_500_returns_status_code(app: Flask, client: FlaskClient) -> None:
    """500 error handler returns HTTP 500."""
    from flask import abort

    @app.route("/test-500-status")
    def _trigger() -> str:
        abort(500)

    with client.session_transaction() as sess:
        sess["user_id"] = 1
    response = client.get("/test-500-status")
    assert response.status_code == 500


def test_500_returns_html_with_error_message(app: Flask, client: FlaskClient) -> None:
    """500 error handler renders the branded error page."""
    from flask import abort

    @app.route("/test-500-html")
    def _trigger_html() -> str:
        abort(500)

    with client.session_transaction() as sess:
        sess["user_id"] = 1
    response = client.get("/test-500-html", headers={"Accept-Language": "en"})
    assert b"Something went wrong" in response.data
    assert b"Try again" in response.data
    assert b"Go to feed" in response.data


def test_500_htmx_request_returns_empty_body(app: Flask, client: FlaskClient) -> None:
    """500 error handler returns empty body for HTMX partial requests."""
    from flask import abort

    @app.route("/test-500-htmx")
    def _trigger_htmx() -> str:
        abort(500)

    with client.session_transaction() as sess:
        sess["user_id"] = 1
    response = client.get("/test-500-htmx", headers={"HX-Request": "true"})
    assert response.status_code == 500
    assert response.data == b""
