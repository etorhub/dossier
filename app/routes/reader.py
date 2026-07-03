"""Reader routes: guided daily reading session, review feed, and stats."""

from typing import Any

from flask import Blueprint, redirect, render_template, request, session, url_for
from flask_babel import gettext

from app.config import load_config
from app.db import reading as db_reading
from app.services import article_service, profile_service, reading_service
from app.services.csrf import validate_csrf_token

reader_bp = Blueprint("reader", __name__)


@reader_bp.route("/")
def index() -> Any:
    """Guided reading session: one story at a time. Redirect to /setup if no profile."""
    user_id = session.get("user_id")
    if not user_id:
        return redirect(url_for("auth.login"))

    profile = profile_service.get_profile_with_selections(user_id)
    if not profile:
        return redirect(url_for("setup.setup_page"))

    config = load_config()
    state = reading_service.get_session_state(user_id, config, profile=profile)

    return render_template("session.html", **state)


@reader_bp.route("/read/advance", methods=["POST"])
def advance() -> Any:
    """Mark the current story read and move to the next (or completion screen)."""
    user_id = session.get("user_id")
    if not user_id:
        return redirect(url_for("auth.login"))

    if not validate_csrf_token(request.form.get("csrf_token", "")):
        return redirect(url_for("reader.index"))

    profile = profile_service.get_profile_with_selections(user_id)
    if not profile:
        return redirect(url_for("setup.setup_page"))

    story_id = request.form.get("story_id", "").strip()
    config = load_config()
    if story_id:
        state = reading_service.mark_read_and_maybe_complete(user_id, story_id, config)
    else:
        state = reading_service.get_session_state(user_id, config, profile=profile)
        state["streak_incremented"] = False

    # No-JS fallback: re-render the session at its new position via a full page.
    if request.headers.get("HX-Request") != "true":
        return redirect(url_for("reader.index"))

    template = (
        "partials/session_complete.html" if state["completed"] else "partials/session_step.html"
    )
    return render_template(template, **state)


@reader_bp.route("/review")
def review() -> Any:
    """Review view: the scrollable feed for revisiting today's stories."""
    user_id = session.get("user_id")
    if not user_id:
        return redirect(url_for("auth.login"))

    profile = profile_service.get_profile_with_selections(user_id)
    if not profile:
        return redirect(url_for("setup.setup_page"))

    feed, rewrites_pending = article_service.get_feed(user_id)
    read_ids = db_reading.get_read_story_ids(user_id, [s["id"] for s in feed])
    return render_template(
        "review.html",
        feed=feed,
        rewrites_pending=rewrites_pending,
        read_ids=read_ids,
        profile=profile,
    )


@reader_bp.route("/feed")
def feed_partial() -> Any:
    """HTMX partial: review feed content. Polled when rewrites are pending."""
    user_id = session.get("user_id")
    if not user_id:
        return redirect(url_for("auth.login"))

    profile = profile_service.get_profile_with_selections(user_id)
    if not profile:
        return redirect(url_for("setup.setup_page"))

    feed, rewrites_pending = article_service.get_feed(user_id)
    read_ids = db_reading.get_read_story_ids(user_id, [s["id"] for s in feed])
    return render_template(
        "partials/feed_content.html",
        feed=feed,
        rewrites_pending=rewrites_pending,
        read_ids=read_ids,
    )


@reader_bp.route("/stats")
def stats() -> Any:
    """Reading stats: current and longest streak, plus today's progress."""
    user_id = session.get("user_id")
    if not user_id:
        return redirect(url_for("auth.login"))

    profile = profile_service.get_profile_with_selections(user_id)
    if not profile:
        return redirect(url_for("setup.setup_page"))

    config = load_config()
    state = reading_service.get_session_state(user_id, config, profile=profile)
    return render_template("stats.html", **state)


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
    """Return article_expanded partial for HTMX swap (used by the review feed)."""
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
    # Reading in review counts toward completing the daily digest (and streak).
    reading_service.mark_read_and_maybe_complete(user_id, story_id, config)
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
    reading_service.mark_read_and_maybe_complete(user_id, story_id, config)
    return render_template("article.html", article=story)
