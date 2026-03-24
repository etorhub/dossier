"""Flask application factory."""

import os
import re
from datetime import datetime
from pathlib import Path

import humanize
from dotenv import load_dotenv
from flask import Flask, Response, redirect, request, session, url_for
from markupsafe import Markup
from flask_babel import Babel

from app.cli import make_admin, seed_sources, show_rewrite_failures
from app.config import load_config
from app.db import users as db_users
from app.routes.auth import auth_bp
from app.routes.pwa import bp as pwa_bp
from app.routes.reader import reader_bp
from app.routes.settings import settings_bp
from app.routes.setup import setup_bp
from app.services import profile_service

load_dotenv()

PUBLIC_ENDPOINTS = {"auth.login", "auth.register", "health", "favicon"}

babel = Babel()


def get_locale() -> str:
    """Return the locale for the current request (user profile or Accept-Language)."""
    user_id = session.get("user_id")
    if user_id:
        profile = db_users.get_profile(user_id)
        if profile and profile.get("language"):
            return profile["language"]
    config = load_config()
    default = config.get("rewriting", {}).get("default_language", "ca")
    return request.accept_languages.best_match(["ca", "es", "en"], default=default)


def create_app(config_path: str | Path | None = None) -> Flask:
    """Create and configure the Flask application."""
    app = Flask(__name__, template_folder="../templates")
    app.config["CONFIG"] = load_config(config_path)
    app.config["SECRET_KEY"] = os.environ.get(
        "SECRET_KEY", "dev-secret-key-change-in-production"
    )
    app.config["VAPID_PUBLIC_KEY"] = os.environ.get("VAPID_PUBLIC_KEY", "")
    app.config["VAPID_PRIVATE_KEY"] = os.environ.get("VAPID_PRIVATE_KEY", "")
    app.config["VAPID_EMAIL"] = os.environ.get(
        "VAPID_EMAIL", "mailto:admin@example.com"
    )
    # Use absolute path so translations load correctly in Docker and all environments
    _translations_dir = Path(__file__).resolve().parent.parent / "translations"
    app.config["BABEL_TRANSLATION_DIRECTORIES"] = str(_translations_dir)

    babel.init_app(app, locale_selector=get_locale)

    @app.before_request
    def require_auth():  # type: ignore[no-untyped-def]
        if request.endpoint in PUBLIC_ENDPOINTS:
            return None
        if request.endpoint is None:
            return None
        if not session.get("user_id"):
            return redirect(url_for("auth.login"))
        return None

    @app.before_request
    def activate_humanize_locale() -> None:
        """Activate humanize locale for naturaltime filter."""
        locale = get_locale()
        # Humanize uses full locale codes (ca_ES, es_ES); we use short codes (ca, es)
        _humanize_locale = {"ca": "ca_ES", "es": "es_ES", "en": None}.get(locale, locale)
        try:
            humanize.activate(_humanize_locale)
        except (FileNotFoundError, OSError):
            humanize.deactivate()

    @app.route("/favicon.ico")
    def favicon() -> Response:
        """No favicon yet; return 204 to avoid 404s in logs."""
        return Response(status=204)

    @app.route("/health")
    def health() -> str:
        """Health check endpoint. Returns HTML per project rules."""
        return "<!DOCTYPE html><html><body><p>ok</p></body></html>"

    @app.template_filter("naturaltime")
    def naturaltime_filter(dt: datetime | None) -> str:
        """Format datetime as relative time (e.g. '5 minutes ago', '2 days ago')."""
        if dt is None:
            return "—"
        return humanize.naturaltime(dt)

    @app.template_filter("bold_md")
    def bold_md_filter(text: str | None) -> Markup:
        """Convert **term** markers to <strong> tags. HTML-escapes input first."""
        if not text:
            return Markup("")
        escaped = str(Markup.escape(text))
        result = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
        return Markup(result)

    app.register_blueprint(auth_bp)
    app.register_blueprint(setup_bp)
    app.register_blueprint(settings_bp)
    app.register_blueprint(reader_bp)
    app.register_blueprint(pwa_bp)

    @app.context_processor
    def inject_admin_flag():  # type: ignore[no-untyped-def]
        """Inject is_admin, current_user_email, profile, and locale for templates."""
        user_id = session.get("user_id")
        if not user_id:
            return {
                "is_admin": False,
                "current_user_email": None,
                "profile": None,
                "locale": get_locale(),
            }
        user = db_users.get_user_by_id(user_id)
        profile = profile_service.get_profile_with_selections(user_id)
        return {
            "is_admin": user.get("is_admin", False) if user else False,
            "current_user_email": user.get("email") if user else None,
            "profile": profile,
            "locale": get_locale(),
        }

    @app.context_processor
    def inject_vapid_key():  # type: ignore[no-untyped-def]
        """Inject VAPID public key for push subscription JS in base.html."""
        return {"vapid_public_key": app.config.get("VAPID_PUBLIC_KEY", "")}

    app.cli.add_command(seed_sources)
    app.cli.add_command(make_admin)
    app.cli.add_command(show_rewrite_failures)

    return app


# For Gunicorn: use app:application (avoids factory detection issues)
application = create_app()
