"""CSRF token generation and validation using the Flask session."""

import secrets

from flask import session


def generate_csrf_token() -> str:
    """Return the session CSRF token, generating one if absent."""
    if "_csrf_token" not in session:
        session["_csrf_token"] = secrets.token_hex(32)
    return str(session["_csrf_token"])


def validate_csrf_token(token: str) -> bool:
    """Return True if *token* matches the one stored in the session."""
    expected = session.get("_csrf_token")
    if not expected or not token:
        return False
    return secrets.compare_digest(str(expected), token)
