"""Setup wizard: initial configuration after registration."""

from typing import Any

from flask import Blueprint, redirect, render_template, request, session, url_for

from app.config import get_topic_info, load_config, load_sources
from app.services import profile_service

setup_bp = Blueprint("setup", __name__, url_prefix="/setup")


def _all_topics(sources: list[dict[str, Any]]) -> list[str]:
    """Collect unique topic ids from sources."""
    seen: set[str] = set()
    result: list[str] = []
    for s in sources:
        for t in s.get("topics", []):
            if t not in seen:
                seen.add(t)
                result.append(t)
    return sorted(result)


def _topic_infos(topic_ids: list[str], config: dict[str, Any]) -> list[dict[str, Any]]:
    """Build list of {id, label, icon, emoji} for each topic."""
    return [{"id": tid, **get_topic_info(tid, config)} for tid in topic_ids]


@setup_bp.route("/", methods=["GET", "POST"])
def setup_page() -> Any:
    """GET: show setup form. POST: save and redirect to /."""
    user_id = session.get("user_id")
    if not user_id:
        return redirect(url_for("auth.login"))

    sources = load_sources()
    topics = _all_topics(sources)

    if request.method == "GET":
        config = load_config()
        languages = config.get("rewriting", {}).get(
            "languages",
            [
                {"id": "ca", "label": "Catalan"},
                {"id": "es", "label": "Spanish"},
                {"id": "en", "label": "English"},
            ],
        )
        topic_infos = _topic_infos(topics, config)
        return render_template(
            "setup.html",
            sources=sources,
            topics=topics,
            topic_infos=topic_infos,
            style_options=profile_service.get_style_options(config),
            languages=languages,
        )

    config = load_config()
    location = request.form.get("location", "").strip() or None
    language = request.form.get("language", "ca").strip()
    preferred_style = profile_service.normalize_preferred_style(
        request.form.get("preferred_style", "neutral"), config
    )
    high_contrast = request.form.get("high_contrast") == "on"
    color_scheme = request.form.get("color_scheme", "").strip() or None

    topic_ids = request.form.getlist("topics")
    if not topic_ids:
        topic_ids = topics

    form_data = {
        "location": location,
        "language": language,
        "preferred_style": preferred_style,
        "high_contrast": high_contrast,
        "color_scheme": color_scheme,
    }
    profile_service.save_setup(user_id, form_data, topic_ids)

    return redirect(url_for("reader.index"))
