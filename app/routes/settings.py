"""Settings page: edit profile after initial setup."""

from typing import Any

from flask import Blueprint, redirect, render_template, request, session, url_for

from app.config import get_topic_info, load_config, load_sources
from app.services import profile_service

settings_bp = Blueprint("settings", __name__, url_prefix="/settings")


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


@settings_bp.route("/", methods=["GET", "POST"])
def settings_page() -> Any:
    """GET: show settings form with current values. POST: update and redirect back."""
    user_id = session.get("user_id")
    if not user_id:
        return redirect(url_for("auth.login"))

    profile = profile_service.get_profile_with_selections(user_id)
    if not profile:
        return redirect(url_for("setup.setup_page"))

    sources = load_sources()
    topics = _all_topics(sources)

    if request.method == "GET":
        config = load_config()
        languages = config.get("rewriting", {}).get(
            "languages",
            [{"id": "ca", "label": "Catalan"}, {"id": "es", "label": "Spanish"}, {"id": "en", "label": "English"}],
        )
        topic_infos = _topic_infos(topics, config)
        return render_template(
            "settings.html",
            profile=profile,
            sources=sources,
            topics=topics,
            topic_infos=topic_infos,
            style_options=profile_service.get_style_options(config),
            languages=languages,
            needs_regeneration_confirmation=False,
        )

    config = load_config()
    location = request.form.get("location", "").strip() or None
    language = request.form.get("language", "ca").strip()
    preferred_style = profile_service.normalize_preferred_style(
        request.form.get("preferred_style", "neutral"), config
    )
    high_contrast = request.form.get("high_contrast") == "on"

    topic_ids = request.form.getlist("topics")
    if not topic_ids:
        topic_ids = topics

    form_data = {
        "location": location,
        "language": language,
        "preferred_style": preferred_style,
        "high_contrast": high_contrast,
    }

    confirm_regenerate = request.form.get("confirm_regenerate") == "1"
    needs_regeneration = profile_service.regeneration_needed(
        profile, form_data, topic_ids
    )

    if needs_regeneration and not confirm_regenerate:
        display_profile = {
            **profile,
            "location": form_data.get("location"),
            "language": form_data.get("language"),
            "preferred_style": form_data.get("preferred_style"),
            "high_contrast": form_data.get("high_contrast"),
            "topic_ids": topic_ids,
        }
        languages = config.get("rewriting", {}).get(
            "languages",
            [{"id": "ca", "label": "Catalan"}, {"id": "es", "label": "Spanish"}, {"id": "en", "label": "English"}],
        )
        topic_infos = _topic_infos(topics, config)
        return render_template(
            "settings.html",
            profile=display_profile,
            sources=sources,
            topics=topics,
            topic_infos=topic_infos,
            style_options=profile_service.get_style_options(config),
            languages=languages,
            needs_regeneration_confirmation=True,
        )

    profile_service.save_setup(user_id, form_data, topic_ids)

    return redirect(url_for("settings.settings_page") + "?saved=1")
