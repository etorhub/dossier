"""PWA support routes — service worker."""

from __future__ import annotations

import logging

from flask import Blueprint, Response, current_app, make_response, send_from_directory

logger = logging.getLogger(__name__)

# Root-level blueprint for the service worker — must be served from / scope
bp_root = Blueprint("pwa_root", __name__)


@bp_root.get("/sw.js")
def service_worker() -> Response:
    """Serve the service worker with an expanded scope header.

    The SW file lives in /static/ but must control the entire app (/).
    The Service-Worker-Allowed header grants that permission.
    """
    static_folder = current_app.static_folder or ""
    response = make_response(send_from_directory(static_folder, "sw.js"))
    response.headers["Service-Worker-Allowed"] = "/"
    response.headers["Content-Type"] = "application/javascript"
    response.headers["Cache-Control"] = "no-cache"
    return response
