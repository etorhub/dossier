"""News sources view."""

from flask import Blueprint, Response, render_template

from app.db import admin as admin_db
from app.db import availability as availability_db

sources_bp = Blueprint("sources", __name__)


@sources_bp.route("/")
def index() -> Response:
    """Sources and feeds list with availability status."""
    feed_health = admin_db.get_feed_health()
    return render_template("ops/sources.html", feed_health=feed_health)


@sources_bp.route("/partials/availability/<int:feed_id>")
def availability_partial(feed_id: int) -> Response:
    """HTMX partial: availability check history for a feed."""
    history = availability_db.get_availability_history(feed_id, limit=20)
    return render_template(
        "ops/partials/availability_history.html",
        feed_id=feed_id,
        history=history,
    )
