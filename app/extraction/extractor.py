"""Batch enrichment orchestrator for article content extraction."""

import logging
import shutil
import sys
import time
from dataclasses import dataclass
from urllib.parse import urlparse

from app.db import articles as db_articles
from app.extraction.trafilatura import extract_article
from app.feed.classifier import classify_article
from app.llm.http_utils import quiet_http_library_info_logs

logger = logging.getLogger(__name__)

# Feed-derived sources often point at unrelated promos or section thumbs.
_UNTRUSTED_FEED_IMAGE_SOURCES = frozenset({"media_thumbnail", "content_html"})


def _render_enrich_progress(
    done: int,
    total: int,
    title: str,
    *,
    frame: int,
) -> None:
    """One-line stderr progress (TTY only). Matches cluster embed job UX."""
    if total <= 0 or not sys.stderr.isatty():
        return
    spin = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
    ch = spin[frame % len(spin)]
    pct = min(100, round(100.0 * done / total)) if total else 0
    bar_w = min(28, max(12, shutil.get_terminal_size((88, 24)).columns - 48))
    filled = min(bar_w, max(0, round(bar_w * done / total)))
    bar_f = "█" * filled + "░" * (bar_w - filled)
    safe = (title or "").replace("\n", " ").strip() or "—"
    if len(safe) > 40:
        safe = safe[:39] + "…"
    sys.stderr.write(
        f"\r\x1b[36m{ch}\x1b[0m enrich \x1b[32m{bar_f}\x1b[0m "
        f"\x1b[1m{done}\x1b[0m/\x1b[1m{total}\x1b[0m {pct}%  "
        f"\x1b[2m{safe}\x1b[0m\x1b[K"
    )
    sys.stderr.flush()


@dataclass
class EnrichmentReport:
    """Summary of an enrichment run."""

    articles_checked: int
    articles_extracted: int
    articles_failed: int
    articles_skipped: int


def _domain_from_url(url: str) -> str:
    """Extract domain from URL for rate limiting."""
    try:
        parsed = urlparse(url)
        return parsed.netloc or url
    except Exception:
        return url


def enrich_articles(
    config: dict,
    *,
    progress_offset: int = 0,
    progress_total: int = 0,
) -> EnrichmentReport:
    """Process articles needing extraction. Returns EnrichmentReport.

    When called from enrich_all_articles, progress_offset and progress_total
    are supplied so the progress bar spans the full bulk rather than each batch.
    """
    extraction_cfg = config.get("extraction", {})
    if not extraction_cfg.get("enabled", True):
        return EnrichmentReport(0, 0, 0, 0)

    batch_size = extraction_cfg.get("batch_size", 30)
    min_content_length = extraction_cfg.get("min_content_length", 200)
    rate_limit = extraction_cfg.get("rate_limit_per_domain", 2.0)
    timeout = extraction_cfg.get("timeout", 30)

    candidates = db_articles.get_articles_needing_extraction(limit=batch_size)
    if not candidates:
        return EnrichmentReport(0, 0, 0, 0)

    # Group by domain for rate limiting
    by_domain: dict[str, list[dict]] = {}
    for art in candidates:
        domain = _domain_from_url(art["url"])
        by_domain.setdefault(domain, []).append(art)

    report = EnrichmentReport(
        articles_checked=0,
        articles_extracted=0,
        articles_failed=0,
        articles_skipped=0,
    )

    min_interval = 1.0 / rate_limit if rate_limit > 0 else 0
    total_candidates = len(candidates)

    with quiet_http_library_info_logs():
        try:
            for _domain, arts in by_domain.items():
                for art in arts:
                    report.articles_checked += 1
                    article_id = art["id"]
                    url = art["url"]
                    full_text = art.get("full_text") or ""
                    raw_text = art.get("raw_text") or ""
                    title = str(art.get("title") or article_id or "")
                    frame = report.articles_checked - 1

                    # Skip if RSS already provided enough content
                    if len(full_text) >= min_content_length:
                        db_articles.update_article_extraction(
                            article_id, full_text, "skipped", "rss"
                        )
                        report.articles_skipped += 1
                        _render_enrich_progress(
                            progress_offset + report.articles_checked,
                            progress_total or total_candidates,
                            title,
                            frame=frame,
                        )
                        continue

                    # Trafilatura: body image from main content; og:image as fallback
                    extracted, body_image_url, og_image_url = extract_article(url, timeout=timeout)

                    existing_src = (art.get("image_source") or "").strip()
                    existing_url = art.get("image_url")

                    image_url: str | None = None
                    image_source: str | None = None
                    replace_image = False

                    if body_image_url:
                        image_url = body_image_url
                        image_source = "article_body"
                        replace_image = True
                    elif not existing_url and og_image_url:
                        image_url = og_image_url
                        image_source = "og_image"
                    elif existing_src in _UNTRUSTED_FEED_IMAGE_SOURCES and og_image_url:
                        image_url = og_image_url
                        image_source = "og_image"
                        replace_image = True

                    if extracted and len(extracted) >= min_content_length:
                        db_articles.update_article_extraction(
                            article_id,
                            extracted,
                            "extracted",
                            "trafilatura",
                            image_url=image_url,
                            image_source=image_source,
                            replace_image=replace_image,
                        )
                        report.articles_extracted += 1
                        # Re-classify with richer full text — catches non-news
                        # that slipped through the title/raw_text check at fetch.
                        if classify_article(title, extracted) == "non_news":
                            db_articles.update_article_type(article_id, "non_news")
                            logger.debug("Re-classified as non_news after extraction: %s", url)
                    else:
                        # Keep raw_text as fallback, mark failed
                        fallback = full_text or raw_text
                        db_articles.update_article_extraction(
                            article_id,
                            fallback or None,
                            "failed",
                            "trafilatura",
                            image_url=image_url,
                            image_source=image_source,
                            replace_image=replace_image,
                        )
                        report.articles_failed += 1
                        logger.debug(
                            "Extraction failed or insufficient for %s (got %d chars)",
                            url,
                            len(extracted or ""),
                        )

                    _render_enrich_progress(
                        progress_offset + report.articles_checked,
                        progress_total or total_candidates,
                        title,
                        frame=frame,
                    )

                    time.sleep(min_interval)
        finally:
            # Only print the newline here when running standalone (no overall
            # progress context). enrich_all_articles prints it after the loop.
            if sys.stderr.isatty() and total_candidates > 0 and progress_total == 0:
                sys.stderr.write("\n")
                sys.stderr.flush()

    return report


def enrich_all_articles(config: dict) -> EnrichmentReport:
    """Process all pending articles in batches until none remain or max rounds hit.

    Returns aggregate EnrichmentReport. Used by scheduler so clustering never
    runs with pending extraction.
    """
    extraction_cfg = config.get("extraction", {})
    if not extraction_cfg.get("enabled", True):
        return EnrichmentReport(0, 0, 0, 0)

    max_rounds = extraction_cfg.get("max_enrichment_rounds", 20)
    aggregate = EnrichmentReport(0, 0, 0, 0)

    # Auto-abandon articles that have been pending too long (dead URLs, paywalls, etc.)
    abandon_hours = extraction_cfg.get("abandon_after_hours", 4)
    if abandon_hours > 0:
        abandoned = db_articles.abandon_stale_pending_articles(abandon_hours)
        if abandoned > 0:
            logger.warning(
                "Abandoned %d stale pending articles (pending > %d hours)",
                abandoned,
                abandon_hours,
            )

    total_pending = db_articles.get_pending_extraction_count()
    if total_pending == 0:
        return aggregate

    logger.info("Enrichment starting: %d articles pending", total_pending)

    for round_num in range(max_rounds):
        pending = db_articles.get_pending_extraction_count()
        if pending == 0:
            break

        report = enrich_articles(
            config,
            progress_offset=aggregate.articles_checked,
            progress_total=total_pending,
        )
        aggregate.articles_checked += report.articles_checked
        aggregate.articles_extracted += report.articles_extracted
        aggregate.articles_failed += report.articles_failed
        aggregate.articles_skipped += report.articles_skipped

        if report.articles_checked == 0:
            break

        remaining = db_articles.get_pending_extraction_count()
        if remaining > 0:
            logger.debug(
                "Enrichment round %d: %d processed, %d pending remaining",
                round_num + 1,
                report.articles_checked,
                remaining,
            )

    if sys.stderr.isatty() and total_pending > 0:
        sys.stderr.write("\n")
        sys.stderr.flush()

    logger.info(
        "Enrichment complete: %d extracted, %d failed, %d skipped",
        aggregate.articles_extracted,
        aggregate.articles_failed,
        aggregate.articles_skipped,
    )
    return aggregate
