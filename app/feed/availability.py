"""Source feed availability checker. Runs HTTP HEAD requests to verify feed reachability."""

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Any

import httpx

from app.config import load_config
from app.db import availability as availability_db
from app.db import sources as sources_db

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 10.0
DEFAULT_USER_AGENT = "Dossier/0.1 (+https://github.com/etorhub/dossier)"


@dataclass
class AvailabilityReport:
    """Summary of an availability check run."""

    feeds_checked: int
    feeds_available: int
    feeds_unavailable: int


def _check_single_feed(
    feed: dict[str, Any], timeout: float, user_agent: str
) -> tuple[int, bool, int | None, int | None, str | None]:
    """Check one feed.

    Returns (feed_id, is_available, http_status, response_time_ms, error_message)."""
    feed_id = feed["id"]
    feed_url = feed["feed_url"]
    start = time.perf_counter()
    try:
        with httpx.Client(
            follow_redirects=True,
            timeout=timeout,
            headers={"User-Agent": user_agent},
        ) as client:
            resp = client.head(feed_url)
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            # Consider 2xx and 3xx as available; some feeds return 405 for HEAD, try GET
            if resp.status_code in (200, 301, 302, 307, 308):
                availability_db.insert_availability_check(
                    feed_id,
                    is_available=True,
                    http_status=resp.status_code,
                    response_time_ms=elapsed_ms,
                )
                return (feed_id, True, resp.status_code, elapsed_ms, None)
            if resp.status_code == 405:
                # HEAD not allowed, try GET with stream (don't read body)
                resp_get = client.get(feed_url)
                elapsed_ms = int((time.perf_counter() - start) * 1000)
                if resp_get.status_code in (200, 301, 302, 307, 308):
                    availability_db.insert_availability_check(
                        feed_id,
                        is_available=True,
                        http_status=resp_get.status_code,
                        response_time_ms=elapsed_ms,
                    )
                    return (feed_id, True, resp_get.status_code, elapsed_ms, None)
            elapsed_ms = int((time.perf_counter() - start) * 1000)
            availability_db.insert_availability_check(
                feed_id,
                is_available=False,
                http_status=resp.status_code,
                response_time_ms=elapsed_ms,
                error_message=f"HTTP {resp.status_code}",
            )
            return (
                feed_id,
                False,
                resp.status_code,
                elapsed_ms,
                f"HTTP {resp.status_code}",
            )
    except Exception as e:
        elapsed_ms = int((time.perf_counter() - start) * 1000)
        err_msg = str(e)
        availability_db.insert_availability_check(
            feed_id,
            is_available=False,
            error_message=err_msg,
        )
        return (feed_id, False, None, elapsed_ms, err_msg)


def check_all_feeds_availability(config: dict[str, Any] | None = None) -> AvailabilityReport:
    """Check all active feeds. Stores results in source_availability_checks."""
    cfg = config or load_config()
    fetcher_cfg = cfg.get("schedule", {}).get("fetcher", {})
    timeout = float(fetcher_cfg.get("request_timeout_seconds", 30))
    if timeout > 10:
        timeout = 10.0  # Cap at 10s for availability checks
    user_agent = fetcher_cfg.get("user_agent", DEFAULT_USER_AGENT)

    feeds = sources_db.get_all_active_feeds()
    available = 0
    unavailable = 0

    max_workers = min(10, max(1, len(feeds)))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_check_single_feed, f, timeout, user_agent): f for f in feeds}
        for future in as_completed(futures):
            try:
                _, is_avail, _, _, _ = future.result()
                if is_avail:
                    available += 1
                else:
                    unavailable += 1
            except Exception as e:
                logger.exception("Availability check failed: %s", e)
                unavailable += 1

    return AvailabilityReport(
        feeds_checked=len(feeds),
        feeds_available=available,
        feeds_unavailable=unavailable,
    )
