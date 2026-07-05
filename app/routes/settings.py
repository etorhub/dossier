"""Settings page: edit profile after initial setup."""

from typing import Any

from flask import Blueprint, redirect, render_template, request, session, url_for

from app.config import load_config, load_sources
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
        return render_template(
            "settings.html",
            profile=profile,
            sources=sources,
            style_options=profile_service.get_style_options(config),
            needs_regeneration_confirmation=False,
        )

    config = load_config()
    location = request.form.get("location", "").strip() or None
    preferred_style = profile_service.normalize_preferred_style(
        request.form.get("preferred_style", "neutral"), config
    )
    high_contrast = request.form.get("high_contrast") == "on"
    color_scheme = request.form.get("color_scheme", "").strip() or None

    topic_ids = topics

    form_data = {
        "location": location,
        "preferred_style": preferred_style,
        "high_contrast": high_contrast,
        "color_scheme": color_scheme,
    }

    confirm_regenerate = request.form.get("confirm_regenerate") == "1"
    needs_regeneration = profile_service.regeneration_needed(profile, form_data, topic_ids)

    if needs_regeneration and not confirm_regenerate:
        display_profile = {
            **profile,
            "location": form_data.get("location"),
            "preferred_style": form_data.get("preferred_style"),
            "high_contrast": form_data.get("high_contrast"),
            "color_scheme": form_data.get("color_scheme"),
            "topic_ids": topic_ids,
        }
        return render_template(
            "settings.html",
            profile=display_profile,
            sources=sources,
            style_options=profile_service.get_style_options(config),
            needs_regeneration_confirmation=True,
        )

    profile_service.save_setup(user_id, form_data, topic_ids)

    return redirect(url_for("settings.settings_page") + "?saved=1")
