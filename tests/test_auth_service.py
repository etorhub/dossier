"""Tests for auth_service: register_user and authenticate_user."""

from unittest.mock import patch

import bcrypt
import pytest

from app.services.auth_service import authenticate_user, register_user


def _make_hash(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


# ---------------------------------------------------------------------------
# register_user
# ---------------------------------------------------------------------------


def test_register_user_creates_user_when_email_free() -> None:
    """register_user calls create_user and returns the new user_id."""
    with (
        patch("app.services.auth_service.users.get_user_by_email", return_value=None),
        patch("app.services.auth_service.users.create_user", return_value=42) as mock_create,
    ):
        uid = register_user("new@example.com", "password123")

    assert uid == 42
    mock_create.assert_called_once()
    email_arg, hash_arg = mock_create.call_args.args
    assert email_arg == "new@example.com"
    # Hash must verify against the plain password
    assert bcrypt.checkpw(b"password123", hash_arg.encode("utf-8"))


def test_register_user_raises_when_email_taken() -> None:
    """register_user raises ValueError when the email already exists."""
    existing = {"id": 1, "email": "taken@example.com"}
    with (
        patch("app.services.auth_service.users.get_user_by_email", return_value=existing),
        pytest.raises(ValueError, match="already registered"),
    ):
        register_user("taken@example.com", "password123")


# ---------------------------------------------------------------------------
# authenticate_user
# ---------------------------------------------------------------------------


def test_authenticate_user_returns_user_id_for_valid_credentials() -> None:
    """authenticate_user returns the user_id when email and password match."""
    pw_hash = _make_hash("correct_password")
    user = {"id": 7, "password_hash": pw_hash, "is_active": True}
    with patch("app.services.auth_service.users.get_user_by_email", return_value=user):
        result = authenticate_user("user@example.com", "correct_password")
    assert result == 7


def test_authenticate_user_returns_none_for_wrong_password() -> None:
    """authenticate_user returns None when the password does not match."""
    pw_hash = _make_hash("correct_password")
    user = {"id": 7, "password_hash": pw_hash, "is_active": True}
    with patch("app.services.auth_service.users.get_user_by_email", return_value=user):
        result = authenticate_user("user@example.com", "wrong_password")
    assert result is None


def test_authenticate_user_returns_none_when_user_not_found() -> None:
    """authenticate_user returns None when no user exists for the email."""
    with patch("app.services.auth_service.users.get_user_by_email", return_value=None):
        result = authenticate_user("ghost@example.com", "password123")
    assert result is None


def test_authenticate_user_returns_none_when_inactive() -> None:
    """authenticate_user returns None when is_active is False."""
    pw_hash = _make_hash("password")
    user = {"id": 3, "password_hash": pw_hash, "is_active": False}
    with patch("app.services.auth_service.users.get_user_by_email", return_value=user):
        result = authenticate_user("inactive@example.com", "password")
    assert result is None


def test_authenticate_user_coerces_id_to_int() -> None:
    """authenticate_user returns an int even when DB gives a string id."""
    pw_hash = _make_hash("pass")
    user = {"id": "99", "password_hash": pw_hash, "is_active": True}
    with patch("app.services.auth_service.users.get_user_by_email", return_value=user):
        result = authenticate_user("x@example.com", "pass")
    assert result == 99
    assert isinstance(result, int)
