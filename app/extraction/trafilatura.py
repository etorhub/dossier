"""Thin wrapper around trafilatura for article body extraction."""

import logging
import re

import trafilatura

logger = logging.getLogger(__name__)

_OG_IMAGE_RE = re.compile(
    r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']',
    re.I,
)
_OG_IMAGE_RE_ALT = re.compile(
    r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
    re.I,
)
# First image trafilatura kept inside extracted <main> (article body), not page chrome.
_MAIN_BLOCK_RE = re.compile(r"<main[^>]*>(.*?)</main>", re.DOTALL | re.I)
_GRAPHIC_SRC_RE = re.compile(
    r"<graphic[^>]+src=[\"']([^\"']+)[\"']",
    re.I,
)


def _first_article_body_image_url(xml_output: str | None) -> str | None:
    """Return src of the first <graphic> inside extracted <main>, if any."""
    if not xml_output or not xml_output.strip():
        return None
    main = _MAIN_BLOCK_RE.search(xml_output)
    if not main:
        return None
    hit = _GRAPHIC_SRC_RE.search(main.group(1))
    if not hit:
        return None
    url = hit.group(1).strip()
    if url.startswith(("http://", "https://")):
        return url
    return None


def _extract_og_image(html: str) -> str | None:
    """Extract og:image URL from HTML. Returns None if not found."""
    for pattern in (_OG_IMAGE_RE, _OG_IMAGE_RE_ALT):
        match = pattern.search(html)
        if match:
            url = match.group(1).strip()
            if url.startswith(("http://", "https://")):
                return url
    return None


def extract_article(
    url: str, timeout: int = 30
) -> tuple[str | None, str | None, str | None]:
    """Fetch URL and extract main article body as plain text.

    Returns (extracted_text, article_body_image_url, og_image_url).

    ``article_body_image_url`` is the first image Trafilatura keeps in the extracted
    main content (``include_images``), i.e. not sidebar / unrelated feed promos.
    ``og_image_url`` is from page meta (can be wrong); used only when body image
    is missing and the caller applies fallback policy.
    """
    try:
        downloaded = trafilatura.fetch_url(url)
    except Exception as e:
        logger.warning("trafilatura fetch failed for %s: %s", url, e)
        return (None, None, None)

    if not downloaded:
        logger.debug("trafilatura fetch returned empty for %s", url)
        return (None, None, None)

    og_image_url = _extract_og_image(downloaded)

    xml_result: str | None = None
    try:
        xml_result = trafilatura.extract(
            downloaded,
            output_format="xml",
            include_images=True,
            include_comments=False,
        )
    except Exception as e:
        logger.debug("trafilatura xml extract for images failed for %s: %s", url, e)

    article_body_image_url = _first_article_body_image_url(xml_result)

    try:
        result = trafilatura.extract(
            downloaded,
            output_format="txt",
            include_comments=False,
        )
    except Exception as e:
        logger.warning("trafilatura extract failed for %s: %s", url, e)
        return (None, article_body_image_url, og_image_url)

    if not result or not result.strip():
        logger.debug("trafilatura extract returned empty for %s", url)
        return (None, article_body_image_url, og_image_url)

    return (result.strip(), article_body_image_url, og_image_url)
