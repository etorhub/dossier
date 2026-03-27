"""Authentication routes: login, register, logout."""

from typing import Any

from flask import Blueprint, abort, redirect, render_template, request, session, url_for
from flask_babel import gettext

from app.db import users as db_users
from app.services import auth_service
from app.services.csrf import validate_csrf_token

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/login", methods=["GET", "POST"])
def login() -> Any:
    """GET: show login form. POST: authenticate and redirect to /."""
    if request.method == "GET":
        return render_template("login.html")
    if not validate_csrf_token(request.form.get("csrf_token", "")):
        abort(403)
    email = request.form.get("email", "").strip()
    password = request.form.get("password", "")
    if not email or not password:
        return render_template(
            "login.html", error=gettext("Email and password are required."), email=email
        )
    user_id = auth_service.authenticate_user(email, password)
    if not user_id:
        return render_template(
            "login.html", error=gettext("Invalid email or password."), email=email
        )
    db_users.update_last_login(user_id)
    session["user_id"] = user_id
    return redirect(url_for("reader.index"))


@auth_bp.route("/register", methods=["GET", "POST"])
def register() -> Any:
    """GET: show registration form. POST: create user and redirect to /setup."""
    if request.method == "GET":
        return render_template("register.html")
    if not validate_csrf_token(request.form.get("csrf_token", "")):
        abort(403)
    email = request.form.get("email", "").strip()
    password = request.form.get("password", "")
    if not email or not password:
        return render_template(
            "register.html",
            error=gettext("Email and password are required."),
            email=email,
        )
    if len(password) < 8:
        return render_template(
            "register.html",
            error=gettext("Password must be at least 8 characters."),
            email=email,
        )
    try:
        user_id = auth_service.register_user(email, password)
    except ValueError:
        return render_template(
            "register.html", error=gettext("Email already registered."), email=email
        )
    session["user_id"] = user_id
    return redirect(url_for("setup.setup_page"))


@auth_bp.route("/logout", methods=["POST"])
def logout() -> Any:
    """Clear session and redirect to login."""
    if not validate_csrf_token(request.form.get("csrf_token", "")):
        abort(403)
    session.clear()
    return redirect(url_for("auth.login"))
