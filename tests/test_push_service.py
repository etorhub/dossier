"""Tests for app/services/push_service.py."""

from __future__ import annotations

from unittest.mock import MagicMock, patch, call_args
import pytest
from app.services.push_service import _NOTIFICATION_BODIES, notify_users_with_new_stories

# ---------------------------------------------------------------------------
# _NOTIFICATION_BODIES
# ---------------------------------------------------------------------------


def test_notification_bodies_has_expected_languages() -> None:
    """_NOTIFICATION_BODIES contains entries for ca, es, and en."""
    assert "ca" in _NOTIFICATION_BODIES
    assert "es" in _NOTIFICATION_BODIES
    assert "en" in _NOTIFICATION_BODIES


def test_notification_bodies_contain_count_placeholder() -> None:
    """Every body template contains the {count} placeholder."""
    for lang, template in _NOTIFICATION_BODIES.items():
        assert "{count}" in template, f"Missing {{count}} in language '{lang}'"


# ---------------------------------------------------------------------------
# notify_users_with_new_stories
# ---------------------------------------------------------------------------


def _make_flask_app(vapid_private_key: str = "private-key") -> MagicMock:
    app = MagicMock()
    app.config.get.side_effect = lambda key, default=None: {
        "VAPID_PRIVATE_KEY": vapid_private_key,
        "VAPID_EMAIL": "mailto:admin@example.com",
    }.get(key, default)
    return app


def test_notify_skips_when_pywebpush_not_installed() -> None:
    """notify_users_with_new_stories is a no-op when pywebpush is not importable."""
    with patch("builtins.__import__", side_effect=ImportError("no module")):
        # Should not raise
        notify_users_with_new_stories(5, app=_make_flask_app())


def test_notify_skips_when_vapid_private_key_missing() -> None:
    """notify_users_with_new_stories skips when VAPID_PRIVATE_KEY is not configured."""
    app = MagicMock()
    app.config.get.return_value = None  # VAPID_PRIVATE_KEY = None

    mock_webpush = MagicMock()
    with patch.dict("sys.modules", {"pywebpush": MagicMock(webpush=mock_webpush, WebPushException=Exception)}):
        notify_users_with_new_stories(5, app=app)

    mock_webpush.assert_not_called()


def test_notify_sends_push_to_each_subscriber() -> None:
    """notify_users_with_new_stories calls webpush once per subscriber."""
    subscriptions = [
        {"endpoint": "https://push1.example.com", "p256dh": "key1", "auth": "auth1", "language": "en"},
        {"endpoint": "https://push2.example.com", "p256dh": "key2", "auth": "auth2", "language": "ca"},
    ]

    mock_webpush = MagicMock()
    mock_module = MagicMock()
    mock_module.webpush = mock_webpush
    mock_module.WebPushException = Exception

    with (
        patch.dict("sys.modules", {"pywebpush": mock_module}),
        patch("app.services.push_service.push_db.get_all_subscriptions_with_language", return_value=subscriptions),
    ):
        notify_users_with_new_stories(3, app=_make_flask_app())

    assert mock_webpush.call_count == 2


def test_notify_uses_correct_language_for_body() -> None:
    """notify_users_with_new_stories uses the subscriber's language for the body."""
    import json

    subscriptions = [
        {"endpoint": "https://push.example.com", "p256dh": "k", "auth": "a", "language": "ca"},
    ]

    sent_payloads: list[str] = []

    def capture_webpush(**kwargs: object) -> None:
        sent_payloads.append(str(kwargs.get("data", "")))

    mock_module = MagicMock()
    mock_module.webpush = capture_webpush
    mock_module.WebPushException = Exception

    with (
        patch.dict("sys.modules", {"pywebpush": mock_module}),
        patch("app.services.push_service.push_db.get_all_subscriptions_with_language", return_value=subscriptions),
    ):
        notify_users_with_new_stories(7, app=_make_flask_app())

    assert len(sent_payloads) == 1
    payload = json.loads(sent_payloads[0])
    # Catalan body should contain "7"
    assert "7" in payload["body"]
    # Catalan body should not be the English fallback
    assert payload["body"] != _NOTIFICATION_BODIES["en"].format(count=7)
    assert payload["body"] == _NOTIFICATION_BODIES["ca"].format(count=7)


def test_notify_falls_back_to_english_for_unknown_language() -> None:
    """notify_users_with_new_stories uses the English body for unrecognised language codes."""
    import json

    subscriptions = [
        {"endpoint": "https://push.example.com", "p256dh": "k", "auth": "a", "language": "fr"},
    ]

    sent_payloads: list[str] = []

    def capture_webpush(**kwargs: object) -> None:
        sent_payloads.append(str(kwargs.get("data", "")))

    mock_module = MagicMock()
    mock_module.webpush = capture_webpush
    mock_module.WebPushException = Exception

    with (
        patch.dict("sys.modules", {"pywebpush": mock_module}),
        patch("app.services.push_service.push_db.get_all_subscriptions_with_language", return_value=subscriptions),
    ):
        notify_users_with_new_stories(4, app=_make_flask_app())

    payload = json.loads(sent_payloads[0])
    assert payload["body"] == _NOTIFICATION_BODIES["en"].format(count=4)


def test_notify_removes_dead_subscription_on_404() -> None:
    """notify_users_with_new_stories deletes a subscription that returns 404 or 410."""
    subscriptions = [
        {"endpoint": "https://dead.example.com", "p256dh": "k", "auth": "a", "language": "en"},
    ]

    # Construct a WebPushException with a response that has status_code 410
    mock_response = MagicMock()
    mock_response.status_code = 410

    class FakeWebPushException(Exception):
        def __init__(self) -> None:
            self.response = mock_response

    mock_module = MagicMock()
    mock_module.webpush = MagicMock(side_effect=FakeWebPushException())
    mock_module.WebPushException = FakeWebPushException

    with (
        patch.dict("sys.modules", {"pywebpush": mock_module}),
        patch("app.services.push_service.push_db.get_all_subscriptions_with_language", return_value=subscriptions),
        patch("app.services.push_service.push_db.delete_subscription") as mock_delete,
    ):
        notify_users_with_new_stories(1, app=_make_flask_app())

    mock_delete.assert_called_once_with("https://dead.example.com")


def test_notify_does_not_remove_subscription_on_other_errors() -> None:
    """notify_users_with_new_stories logs but does not delete on non-404/410 errors."""
    subscriptions = [
        {"endpoint": "https://flaky.example.com", "p256dh": "k", "auth": "a", "language": "en"},
    ]

    mock_response = MagicMock()
    mock_response.status_code = 500

    class FakeWebPushException(Exception):
        def __init__(self) -> None:
            self.response = mock_response

    mock_module = MagicMock()
    mock_module.webpush = MagicMock(side_effect=FakeWebPushException())
    mock_module.WebPushException = FakeWebPushException

    with (
        patch.dict("sys.modules", {"pywebpush": mock_module}),
        patch("app.services.push_service.push_db.get_all_subscriptions_with_language", return_value=subscriptions),
        patch("app.services.push_service.push_db.delete_subscription") as mock_delete,
    ):
        notify_users_with_new_stories(1, app=_make_flask_app())

    mock_delete.assert_not_called()
