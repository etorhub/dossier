"""User profile and setup wizard logic."""

from typing import Any

from app.db import users


def get_style_options(config: dict[str, Any]) -> list[tuple[str, str]]:
    """(style_id, label) pairs from rewriting.styles for setup/settings selects."""
    styles = config.get("rewriting", {}).get("styles", [])
    out: list[tuple[str, str]] = []
    for s in styles:
        if isinstance(s, dict):
            sid = s.get("id")
            if isinstance(sid, str) and sid.strip():
                label = s.get("label", sid)
                out.append((sid.strip(), str(label)))
    if not out:
        return [("neutral", "Neutral")]
    return out


def normalize_preferred_style(preferred_style: str, config: dict[str, Any]) -> str:
    """Clamp submitted style to ids declared in rewriting.styles."""
    allowed = {sid for sid, _ in get_style_options(config)}
    p = (preferred_style or "").strip()
    if p in allowed:
        return p
    rewriting = config.get("rewriting", {})
    return str(rewriting.get("default_style", "neutral"))


def get_reading_variant(
    profile: dict[str, Any],
    config: dict[str, Any],
) -> tuple[str, str]:
    """Return (style, language) for feed selection, with config fallback."""
    rewriting = config.get("rewriting", {})
    styles = [s["id"] for s in rewriting.get("styles", [])]
    languages = [l["id"] for l in rewriting.get("languages", [])]
    default_style = rewriting.get("default_style", "neutral")
    default_language = rewriting.get("default_language", "ca")

    style = (profile.get("preferred_style") or default_style).strip() or default_style
    language = (profile.get("language") or default_language).strip() or default_language

    if style not in styles:
        style = default_style
    if language not in languages:
        language = default_language
    return (style, language)


def regeneration_needed(
    old_profile: dict[str, Any],
    new_form_data: dict[str, Any],
    new_topic_ids: list[str],
) -> bool:
    """Return True if any regeneration-affecting field changed."""
    old_topics = set(old_profile.get("topic_ids", []))
    new_topics = set(new_topic_ids)
    if old_topics != new_topics:
        return True
    if (old_profile.get("location") or None) != (new_form_data.get("location") or None):
        return True
    if old_profile.get("language", "ca") != new_form_data.get("language", "ca"):
        return True
    return old_profile.get("preferred_style", "neutral") != new_form_data.get(
        "preferred_style", "neutral"
    )


def save_setup(
    user_id: int,
    form_data: dict[str, Any],
    topic_ids: list[str],
) -> None:
    """Create or update profile and save topic selections."""
    style = form_data.get("preferred_style", "neutral")
    tone_map = {
        "neutral": "Journalistic style. Formal and well-written. Do not simplify; preserve original complexity and nuance. Avoid spoilers in headlines or summaries.",
        "simple": "Short sentences. Simple vocabulary. No jargon.",
    }
    profile_data = {
        "location": form_data.get("location"),
        "language": form_data.get("language", "ca"),
        "rewrite_tone": form_data.get("rewrite_tone") or tone_map.get(style, tone_map["neutral"]),
        "high_contrast": form_data.get("high_contrast", False),
        "preferred_style": style,
        "color_scheme": form_data.get("color_scheme") or None,
    }
    existing = users.get_profile(user_id)
    if existing:
        users.update_profile(user_id, profile_data)
    else:
        users.create_profile(user_id, profile_data)
    users.set_user_topics(user_id, topic_ids)


def get_profile_with_selections(user_id: int) -> dict[str, Any]:
    """Return profile dict with topic_ids list."""
    profile = users.get_profile(user_id)
    if not profile:
        return {}
    return {**profile, "topic_ids": users.get_user_topics(user_id)}
