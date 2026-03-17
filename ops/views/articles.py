"""Articles view."""

from flask import Blueprint, Response, render_template, request

from app.db import admin as admin_db
from app.db import sources as sources_db

articles_bp = Blueprint("articles", __name__)


@articles_bp.route("/")
def index() -> Response:
    """Articles list with filters and pagination."""
    page = max(1, request.args.get("page", 1, type=int))
    per_page = min(100, max(10, request.args.get("per_page", 50, type=int)))
    extraction_status = request.args.get("extraction_status") or None
    source_id = request.args.get("source_id") or None
    date_from = request.args.get("date_from") or None
    date_to = request.args.get("date_to") or None
    _he = request.args.get("has_embedding")
    has_embedding: bool | None = True if _he == "1" else (False if _he == "0" else None)
    _is = request.args.get("in_story")
    in_story: bool | None = True if _is == "1" else (False if _is == "0" else None)

    total = admin_db.get_admin_articles_count(
        extraction_status=extraction_status,
        source_id=source_id,
        date_from=date_from,
        date_to=date_to,
        has_embedding=has_embedding,
        in_story=in_story,
    )
    offset = (page - 1) * per_page
    articles = admin_db.get_admin_articles(
        limit=per_page,
        offset=offset,
        extraction_status=extraction_status,
        source_id=source_id,
        date_from=date_from,
        date_to=date_to,
        has_embedding=has_embedding,
        in_story=in_story,
    )
    sources = sources_db.get_all_sources(status=None)

    return render_template(
        "ops/articles.html",
        articles=articles,
        total=total,
        page=page,
        per_page=per_page,
        sources=sources,
        extraction_status=extraction_status,
        source_id=source_id,
        date_from=date_from,
        date_to=date_to,
        has_embedding=has_embedding,
        in_story=in_story,
    )


@articles_bp.route("/partials/detail/<article_id>")
def article_detail_partial(article_id: str) -> Response:
    """HTMX partial: full article content (title, summary, text, etc)."""
    article = admin_db.get_admin_article_by_id(article_id)
    return render_template(
        "ops/partials/article_detail.html",
        article=article,
    )
