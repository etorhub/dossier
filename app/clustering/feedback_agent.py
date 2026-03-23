"""Review clustering_feedback rows: LLM analysis and optional exclusion rules."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any

from app.clustering.retroactive_rules import apply_article_pair_rules_retroactively
from app.config import load_config
from app.db import admin as admin_db
from app.db import articles as articles_db
from app.db import stories as stories_db
from app.llm.prompts import load_prompt
from app.llm.provider import LLMProviderError, get_provider

from app.clustering.vectors import cosine_similarity, embedding_from_article

logger = logging.getLogger(__name__)


@dataclass
class FeedbackReviewReport:
    """Summary of a feedback review run."""

    rows_processed: int
    rules_created: int
    retroactive_removals: int


def _excerpt(article: dict[str, Any], max_len: int = 1200) -> str:
    full = (article.get("full_text") or "").strip()
    raw = (article.get("raw_text") or "").strip()
    body = full or raw
    body = body[:max_len] if body else ""
    return body.replace("\n", " ").strip() or "(no text)"


def _parse_llm_json(text: str) -> dict[str, Any] | None:
    raw = text.strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", raw)
    if fence:
        raw = fence.group(1).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            try:
                return json.loads(raw[start : end + 1])
            except json.JSONDecodeError:
                pass
    return None


def _build_story_block(articles: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for a in articles:
        lines.append(
            f"id: {a['id']}\nsource_id: {a.get('source_id') or ''}\n"
            f"title: {(a.get('title') or '')[:200]}\n"
            f"text_excerpt: {_excerpt(a, 800)}\n---"
        )
    return "\n".join(lines) if lines else "(no other articles remain in this story)"


def _build_diagnostics(flagged: dict[str, Any], others: list[dict[str, Any]]) -> str:
    emb_f = embedding_from_article(flagged)
    if not emb_f:
        return "(flagged article has no embedding)"
    lines: list[str] = []
    for a in others:
        emb_o = embedding_from_article(a)
        if not emb_o:
            lines.append(f"{a['id']}: (no embedding)")
            continue
        sim = cosine_similarity(emb_f, emb_o)
        lines.append(f"{a['id']}: {sim:.4f}")
    return "\n".join(lines) if lines else "(no peers)"


def _validate_article_pair(
    data: dict[str, Any],
    flagged_id: str,
    allowed_ids: set[str],
) -> dict[str, Any] | None:
    a = data.get("article_id_a")
    b = data.get("article_id_b")
    if not isinstance(a, str) or not isinstance(b, str):
        return None
    if a not in allowed_ids or b not in allowed_ids:
        logger.warning("LLM article_pair ids not in allowed set; skipping rule")
        return None
    if a == b:
        return None
    return {"article_id_a": a, "article_id_b": b}


def _validate_source_pair(data: dict[str, Any], allowed_sources: set[str]) -> dict[str, Any] | None:
    sa = data.get("source_a")
    sb = data.get("source_b")
    if not isinstance(sa, str) or not isinstance(sb, str):
        return None
    if sa not in allowed_sources or sb not in allowed_sources:
        logger.warning("LLM source_pair ids not in allowed set; skipping rule")
        return None
    try:
        ms = float(data.get("min_similarity", 0.93))
    except (TypeError, ValueError):
        ms = 0.93
    ms = max(0.88, min(0.98, ms))
    return {"source_a": sa, "source_b": sb, "min_similarity": ms}


def _finalize_feedback(
    feedback_id: str,
    *,
    status: str,
    agent_analysis: str,
    agent_recommendation: str = "",
) -> None:
    admin_db.update_clustering_feedback_review(
        feedback_id,
        status=status,
        agent_analysis=agent_analysis,
        agent_recommendation=agent_recommendation,
    )


def _process_one_pending(feedback_id: str, article_id: str, story_id: str) -> bool:
    """Run LLM review for one row. Returns True if an exclusion rule was inserted."""
    flagged = articles_db.get_article_by_id(article_id)
    if not flagged:
        _finalize_feedback(
            feedback_id,
            status="failed",
            agent_analysis="Article not found in database.",
        )
        return False

    others = stories_db.get_articles_in_story(story_id)
    allowed_article_ids = {article_id, *(a["id"] for a in others)}
    allowed_sources = {
        (flagged.get("source_id") or "").strip(),
        *((a.get("source_id") or "").strip() for a in others),
    }
    allowed_sources.discard("")

    diag = _build_diagnostics(flagged, others)
    story_block = _build_story_block(others)
    try:
        template = load_prompt("clustering_review")
        prompt = template.format(
            flagged_article_id=article_id,
            flagged_source_id=(flagged.get("source_id") or ""),
            flagged_title=(flagged.get("title") or "")[:500],
            flagged_excerpt=_excerpt(flagged, 1500),
            story_articles_block=story_block,
            diagnostics_block=diag,
        )
    except (KeyError, ValueError) as e:
        logger.warning("Clustering review prompt format failed for %s: %s", feedback_id, e)
        _finalize_feedback(
            feedback_id,
            status="failed",
            agent_analysis=f"Prompt/template error: {e}",
        )
        return False

    cfg = load_config()
    llm = cfg.get("llm", {})
    temperature = float(llm.get("rewrite_temperature", 0.2))
    provider = get_provider(cfg)
    try:
        raw_out = provider.complete(prompt, max_tokens=2048, temperature=temperature)
    except LLMProviderError as e:
        logger.warning("Clustering review LLM failed for %s: %s", feedback_id, e)
        _finalize_feedback(
            feedback_id,
            status="failed",
            agent_analysis=f"LLM error: {e}",
        )
        return False

    parsed = _parse_llm_json(raw_out)
    if not parsed:
        _finalize_feedback(
            feedback_id,
            status="failed",
            agent_analysis=f"Unparseable LLM output (first 500 chars): {raw_out[:500]!r}",
        )
        return False

    analysis = str(parsed.get("analysis") or "").strip()
    recommendation = str(parsed.get("recommendation") or "").strip()
    confidence = str(parsed.get("confidence") or "low").lower()
    rule_type = parsed.get("rule_type")
    rule_data = parsed.get("rule_data")

    def _reviewed_no_rule() -> None:
        _finalize_feedback(
            feedback_id,
            status="reviewed",
            agent_analysis=analysis or raw_out[:2000],
            agent_recommendation=recommendation,
        )

    if confidence != "high":
        _reviewed_no_rule()
        return False

    if rule_type is None or (
        isinstance(rule_type, str) and rule_type.strip().lower() in ("", "null", "none")
    ):
        _reviewed_no_rule()
        return False

    if not isinstance(rule_data, dict):
        _finalize_feedback(
            feedback_id,
            status="failed",
            agent_analysis=(analysis or "")
            + " [Agent error: confidence was high but rule_data was not a JSON object.]",
            agent_recommendation=recommendation,
        )
        return False

    desc = f"{rule_type}: {recommendation[:200]}" if recommendation else str(rule_type)
    rt = str(rule_type).strip().lower()

    if rt == "article_pair":
        clean = _validate_article_pair(rule_data, article_id, allowed_article_ids)
        if not clean:
            _finalize_feedback(
                feedback_id,
                status="failed",
                agent_analysis=(analysis or "")
                + " [Rule validation failed: article_pair ids invalid or not in context.]",
                agent_recommendation=recommendation,
            )
            return False
        admin_db.insert_clustering_exclusion_rule(
            feedback_id, "article_pair", clean, desc
        )
        _finalize_feedback(
            feedback_id,
            status="reviewed",
            agent_analysis=analysis or raw_out[:2000],
            agent_recommendation=recommendation,
        )
        return True

    if rt == "source_pair":
        clean = _validate_source_pair(rule_data, allowed_sources)
        if not clean:
            _finalize_feedback(
                feedback_id,
                status="failed",
                agent_analysis=(analysis or "")
                + " [Rule validation failed: source_pair invalid or sources not in context.]",
                agent_recommendation=recommendation,
            )
            return False
        admin_db.insert_clustering_exclusion_rule(
            feedback_id, "source_pair", clean, desc
        )
        _finalize_feedback(
            feedback_id,
            status="reviewed",
            agent_analysis=analysis or raw_out[:2000],
            agent_recommendation=recommendation,
        )
        return True

    if rt == "keyword":
        kw = rule_data.get("keyword")
        if not isinstance(kw, str) or not kw.strip():
            _finalize_feedback(
                feedback_id,
                status="failed",
                agent_analysis=(analysis or "")
                + " [Rule validation failed: keyword rule missing keyword.]",
                agent_recommendation=recommendation,
            )
            return False
        note = str(rule_data.get("note") or "")
        admin_db.insert_clustering_exclusion_rule(
            feedback_id,
            "keyword",
            {"keyword": kw.strip(), "note": note[:500]},
            desc,
        )
        _finalize_feedback(
            feedback_id,
            status="reviewed",
            agent_analysis=analysis or raw_out[:2000],
            agent_recommendation=recommendation,
        )
        return True

    _finalize_feedback(
        feedback_id,
        status="failed",
        agent_analysis=(analysis or "")
        + f" [Agent error: unknown rule_type {rule_type!r} with high confidence.]",
        agent_recommendation=recommendation,
    )
    return False


def run_feedback_review() -> FeedbackReviewReport:
    """Process pending and failed clustering_feedback rows; apply article_pair rules retroactively."""
    pending = admin_db.get_pending_clustering_feedback()
    rules = 0
    n_processed = 0
    for row in pending:
        fid = row["id"]
        aid = row["article_id"]
        sid = row["story_id"]
        try:
            if _process_one_pending(fid, aid, sid):
                rules += 1
        except Exception:
            logger.exception("Feedback review failed for %s", fid)
            _finalize_feedback(
                fid,
                status="failed",
                agent_analysis="Internal error during review (see worker logs).",
            )
        n_processed += 1

    retro = apply_article_pair_rules_retroactively()
    if retro:
        logger.info("Retroactive article_pair enforcement: %d story membership(s) removed", retro)

    return FeedbackReviewReport(
        rows_processed=n_processed,
        rules_created=rules,
        retroactive_removals=retro,
    )
