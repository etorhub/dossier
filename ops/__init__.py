"""Ops dashboard Flask application. Separate from the main Dossier web app."""

import json
import os
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask

from ops.views.dashboard import dashboard_bp
from ops.views.jobs import jobs_bp
from ops.views.sources import sources_bp
from ops.views.articles import articles_bp
from ops.views.stories import stories_bp
from ops.views.users import users_bp

load_dotenv()


def create_app() -> Flask:
    """Create and configure the ops Flask application."""
    template_dir = Path(__file__).resolve().parent / "templates"
    app = Flask(__name__, template_folder=str(template_dir))
    app.config["SECRET_KEY"] = os.environ.get(
        "SECRET_KEY", "ops-dev-secret-change-in-production"
    )

    app.register_blueprint(dashboard_bp, url_prefix="/")
    app.register_blueprint(jobs_bp, url_prefix="/jobs")
    app.register_blueprint(sources_bp, url_prefix="/sources")
    app.register_blueprint(articles_bp, url_prefix="/articles")
    app.register_blueprint(stories_bp, url_prefix="/stories")
    app.register_blueprint(users_bp, url_prefix="/users")

    @app.template_filter("tojson")
    def tojson_filter(obj):
        """JSON serialize for template display."""
        return json.dumps(obj, indent=2, default=str) if obj is not None else ""

    return app


application = create_app()
