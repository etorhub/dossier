"""Stories (clusters) view."""

from typing import Any
from uuid import UUID

from flask import Blueprint, Response, render_template, request

from app.config import load_config
from app.db import admin as admin_db

stories_bp = Blueprint("stories", __name__)


@stories_bp.route("/")
def index() -> Response:
    """Stories list with rewrite status matrix."""
    config = load_config()
    page = max(1, request.args.get("page", 1, type=int))
    per_page = min(100, max(10, request.args.get("per_page", 50, type=int)))

    story_raw = (request.args.get("story") or "").strip()
    story_id: str | None = None
    story_invalid = False
    if story_raw:
        try:
            story_id = str(UUID(story_raw))
        except ValueError:
            story_invalid = True

    if story_invalid:
        total = 0
        stories: list[dict[str, Any]] = []
    else:
        total = admin_db.get_admin_stories_count(story_id=story_id)
        offset = (page - 1) * per_page
        stories = admin_db.get_stories_with_rewrite_status(
            limit=per_page,
            offset=offset,
            config=config,
            story_id=story_id,
        )

    return render_template(
        "ops/stories.html",
        stories=stories,
        total=total,
        page=page,
        per_page=per_page,
        story_filter=story_raw,
        story_invalid=story_invalid,
    )


@stories_bp.route("/partials/detail/<story_id>")
def story_detail_partial(story_id: str) -> Response:
    """HTMX partial: story articles and rewrite details."""
    articles = admin_db.get_admin_story_articles(story_id)
    return render_template(
        "ops/partials/story_detail.html",
        story_id=story_id,
        articles=articles,
    )
