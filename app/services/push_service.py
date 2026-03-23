"""Push notification service — sends web push messages to subscribed users."""
from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)

# Localised notification bodies — must NOT use Flask-Babel (runs outside request context in worker)
_NOTIFICATION_BODIES: dict[str, str] = {
    "ca": "Tens {count} notícies noves",
    "es": "Tienes {count} noticias nuevas",
    "en": "{count} new stories ready for you",
}


def notify_users_with_new_stories(story_count: int, app: object = None) -> None:
    """Send push notifications to all subscribed users.

    Must be called with a Flask app instance (or from within app context) so that
    config values (VAPID keys) are accessible.

    Args:
        story_count: Number of new stories that are ready.
        app: Flask app instance (used to read VAPID config).
    """
    try:
        from pywebpush import WebPushException, webpush
    except ImportError:
        logger.warning("pywebpush not installed — push notifications skipped")
        return

    from app.db import push_subscriptions as push_db

    if app is None:
        from flask import current_app

        app = current_app._get_current_object()

    vapid_private_key = app.config.get("VAPID_PRIVATE_KEY")  # type: ignore[union-attr]
    vapid_email = app.config.get("VAPID_EMAIL", "mailto:admin@example.com")  # type: ignore[union-attr]

    if not vapid_private_key:
        logger.warning("VAPID_PRIVATE_KEY not configured — push notifications skipped")
        return

    subscriptions = push_db.get_all_subscriptions_with_language()
    logger.info("Sending push notifications to %d subscribers", len(subscriptions))

    for sub in subscriptions:
        lang = sub.get("language", "en")
        body_template = _NOTIFICATION_BODIES.get(lang, _NOTIFICATION_BODIES["en"])
        body = body_template.format(count=story_count)
        payload = json.dumps({"title": "Dossier", "body": body, "url": "/"})

        try:
            webpush(
                subscription_info={
                    "endpoint": sub["endpoint"],
                    "keys": {"p256dh": sub["p256dh"], "auth": sub["auth"]},
                },
                data=payload,
                vapid_private_key=vapid_private_key,
                vapid_claims={"sub": vapid_email},
            )
        except WebPushException as ex:
            if ex.response is not None and ex.response.status_code in (404, 410):
                # Subscription is expired/invalid — remove it
                logger.info(
                    "Removing dead push subscription: %s", sub["endpoint"][:50]
                )
                push_db.delete_subscription(sub["endpoint"])
            else:
                logger.warning(
                    "Push failed for endpoint %s: %s", sub["endpoint"][:50], ex
                )
