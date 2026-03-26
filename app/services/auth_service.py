"""User registration and authentication."""

import bcrypt

from app.db import users


def register_user(email: str, password: str) -> int:
    """Create a new user. Returns user_id. Raises ValueError if email already exists."""
    existing = users.get_user_by_email(email)
    if existing:
        raise ValueError("Email already registered")
    password_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    return users.create_user(email, password_hash)


def authenticate_user(email: str, password: str) -> int | None:
    """Verify credentials. Returns user_id if valid, None otherwise."""
    user = users.get_user_by_email(email)
    if not user or not user.get("is_active"):
        return None
    if not bcrypt.checkpw(password.encode("utf-8"), user["password_hash"].encode("utf-8")):
        return None
    return int(user["id"])
