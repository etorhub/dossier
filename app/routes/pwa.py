"""PWA support routes — push notification subscription management."""
from __future__ import annotations

import json
import logging

from flask import Blueprint, render_template_string, request, session

from app.db import push_subscriptions as push_db

logger = logging.getLogger(__name__)
bp = Blueprint("pwa", __name__, url_prefix="/pwa")


def _require_login() -> int | None:
    """Return user_id or None if not logged in."""
    return session.get("user_id")


@bp.post("/subscribe")
def subscribe() -> tuple[str, int] | str:
    """Save a push subscription for the current user."""
    user_id = _require_login()
    if not user_id:
        return render_template_string(""), 401

    raw = request.form.get("subscription", "")
    if not raw:
        return render_template_string(""), 400

    try:
        sub = json.loads(raw)
        endpoint = sub["endpoint"]
        p256dh = sub["keys"]["p256dh"]
        auth = sub["keys"]["auth"]
    except (KeyError, json.JSONDecodeError, TypeError) as ex:
        logger.debug("Invalid subscription payload: %s", ex)
        return render_template_string(""), 400

    try:
        push_db.save_subscription(user_id, endpoint, p256dh, auth)
    except Exception as ex:
        logger.error("Failed to save push subscription: %s", ex)
        return render_template_string(""), 500

    return render_template_string("")


@bp.post("/unsubscribe")
def unsubscribe() -> tuple[str, int] | str:
    """Remove the push subscription for the current user."""
    user_id = _require_login()
    if not user_id:
        return render_template_string(""), 401

    raw = request.form.get("endpoint", "")
    if raw:
        try:
            push_db.delete_subscription(raw)
        except Exception as ex:
            logger.error("Failed to delete push subscription: %s", ex)

    return render_template_string("")
