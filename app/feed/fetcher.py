"""HTTP fetcher for RSS/Atom feeds with conditional GET support."""

from dataclasses import dataclass

import httpx


@dataclass
class FetchResult:
    """Result of a feed fetch."""

    status_code: int
    content: bytes | None
    etag: str | None
    last_modified: str | None
    is_not_modified: bool


def fetch_feed(
    feed_url: str,
    etag: str | None = None,
    last_modified: str | None = None,
    *,
    timeout: float = 30.0,
    user_agent: str = "Dossier/0.1",
) -> FetchResult:
    """Fetch a feed via HTTP GET with optional conditional headers.

    Returns FetchResult. If status is 304, is_not_modified is True and content
    is None. Otherwise content holds the response body.
    """
    headers: dict[str, str] = {}
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified
    headers["User-Agent"] = user_agent

    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            response = client.get(feed_url, headers=headers or None)
    except httpx.HTTPError:
        raise  # Caller handles

    response_etag = response.headers.get("ETag")
    response_last_modified = response.headers.get("Last-Modified")

    if response.status_code == 304:
        return FetchResult(
            status_code=304,
            content=None,
            etag=response_etag or etag,
            last_modified=response_last_modified or last_modified,
            is_not_modified=True,
        )

    return FetchResult(
        status_code=response.status_code,
        content=response.content if response.status_code == 200 else None,
        etag=response_etag,
        last_modified=response_last_modified,
        is_not_modified=False,
    )
