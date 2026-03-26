"""Reader routes: main feed and article expansion."""

from typing import Any

from flask import Blueprint, redirect, render_template, request, session, url_for
from flask_babel import gettext

from app.config import get_topic_info, load_config
from app.services import article_service, profile_service

reader_bp = Blueprint("reader", __name__)


def _sections_for_user(profile: dict[str, Any], config: dict[str, Any]) -> list[dict[str, Any]]:
    """Build section list from user's topic_ids with labels and icons."""
    topic_ids = profile.get("topic_ids", [])
    return [{"id": tid, **get_topic_info(tid, config)} for tid in sorted(topic_ids)]


@reader_bp.route("/")
def index() -> Any:
    """Main feed view. Redirect to /setup if no profile. Optional ?topic=X filters by section."""
    user_id = session.get("user_id")
    if not user_id:
        return redirect(url_for("auth.login"))

    profile = profile_service.get_profile_with_selections(user_id)
    if not profile:
        return redirect(url_for("setup.setup_page"))

    topic_filter = request.args.get("topic") or None
    if topic_filter and topic_filter not in set(profile.get("topic_ids", [])):
        topic_filter = None

    config = load_config()
    feed, rewrites_pending = article_service.get_feed(user_id, topic_filter=topic_filter)
    sections = _sections_for_user(profile, config)

    return render_template(
        "index.html",
        feed=feed,
        rewrites_pending=rewrites_pending,
        profile=profile,
        sections=sections,
        topic_filter=topic_filter,
    )


@reader_bp.route("/feed")
def feed_partial() -> Any:
    """HTMX partial: feed content. Polled when rewrites are pending. Accepts ?topic=X."""
    user_id = session.get("user_id")
    if not user_id:
        return redirect(url_for("auth.login"))

    profile = profile_service.get_profile_with_selections(user_id)
    if not profile:
        return redirect(url_for("setup.setup_page"))

    topic_filter = request.args.get("topic") or None
    if topic_filter and topic_filter not in set(profile.get("topic_ids", [])):
        topic_filter = None

    feed, rewrites_pending = article_service.get_feed(user_id, topic_filter=topic_filter)
    return render_template(
        "partials/feed_content.html",
        feed=feed,
        rewrites_pending=rewrites_pending,
        topic_filter=topic_filter,
    )


@reader_bp.route("/clusters/<cluster_id>/expand")
def redirect_expand_cluster(cluster_id: str) -> Any:
    """Redirect old cluster URL to new story URL."""
    return redirect(url_for("reader.expand_story", story_id=cluster_id), code=301)


@reader_bp.route("/clusters/<cluster_id>/collapse")
def redirect_collapse_cluster(cluster_id: str) -> Any:
    """Redirect old cluster URL to new story URL."""
    return redirect(url_for("reader.collapse_story", story_id=cluster_id), code=301)


@reader_bp.route("/stories/<story_id>/expand")
def expand_story(story_id: str) -> Any:
    """Return article_expanded partial for HTMX swap."""
    user_id = session.get("user_id")
    if not user_id:
        return redirect(url_for("auth.login"))

    profile = profile_service.get_profile_with_selections(user_id)
    if not profile:
        return redirect(url_for("setup.setup_page"))

    config = load_config()
    style, language = profile_service.get_reading_variant(profile, config)
    story = article_service.get_expanded_story(story_id, style, language, config)
    archive = request.args.get("archive") == "1"
    if not story:
        return render_template(
            "partials/article_expanded.html",
            article=None,
            error=gettext("Article not found."),
            archive=archive,
        )
    return render_template(
        "partials/article_expanded.html",
        article=story,
        archive=archive,
    )


@reader_bp.route("/stories/<story_id>/collapse")
def collapse_story(story_id: str) -> Any:
    """Return article_card partial for HTMX swap (collapse expanded view)."""
    user_id = session.get("user_id")
    if not user_id:
        return redirect(url_for("auth.login"))

    profile = profile_service.get_profile_with_selections(user_id)
    if not profile:
        return redirect(url_for("setup.setup_page"))

    config = load_config()
    style, language = profile_service.get_reading_variant(profile, config)
    story = article_service.get_expanded_story(story_id, style, language, config)
    archive = request.args.get("archive") == "1"
    if not story:
        return render_template(
            "partials/article_expanded.html",
            article=None,
            error=gettext("Article not found."),
            archive=archive,
        )
    return render_template(
        "partials/article_card.html",
        article=story,
        archive=archive,
    )


@reader_bp.route("/article/<story_id>")
def article_page(story_id: str) -> Any:
    """Full-page article view."""
    user_id = session.get("user_id")
    if not user_id:
        return redirect(url_for("auth.login"))

    profile = profile_service.get_profile_with_selections(user_id)
    if not profile:
        return redirect(url_for("setup.setup_page"))

    config = load_config()
    style, language = profile_service.get_reading_variant(profile, config)
    story = article_service.get_expanded_story(story_id, style, language, config)
    if not story:
        return render_template("article.html", article=None, error=gettext("Article not found."))
    return render_template("article.html", article=story)
