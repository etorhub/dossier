"""Apply article_pair exclusion rules to existing story memberships (retroactive)."""

from __future__ import annotations

import logging

from app.clustering.vectors import recompute_story_centroid
from app.db import admin as admin_db
from app.db import stories as stories_db

logger = logging.getLogger(__name__)


def apply_article_pair_rules_retroactively() -> int:
    """Detach articles so no story still contains both ends of an active article_pair rule.

    If the rule has a feedback_id, prefer removing the operator-flagged ``article_id``
    from that feedback row when it matches one of the pair and is still in the story.
    Otherwise removes ``article_id_b`` (stable fallback).

    Returns the number of successful removals (membership rows deleted).
    """
    rules = admin_db.get_active_exclusion_rules()
    removed = 0
    for r in rules:
        if r.get("rule_type") != "article_pair":
            continue
        rd = r.get("rule_data")
        if not isinstance(rd, dict):
            continue
        a = rd.get("article_id_a")
        b = rd.get("article_id_b")
        if not isinstance(a, str) or not isinstance(b, str) or not a or not b:
            continue

        smap = stories_db.get_story_ids_for_articles([a, b])
        sa = smap.get(a)
        sb = smap.get(b)
        if not sa or sa != sb:
            continue
        story_id = sa

        remove_id: str | None = None
        fid = r.get("feedback_id")
        if fid:
            flagged_article = admin_db.get_clustering_feedback_flagged_article_id(str(fid))
            if flagged_article and flagged_article in (a, b):
                remove_id = flagged_article

        if remove_id is None:
            remove_id = b

        if stories_db.remove_article_from_story(story_id, remove_id):
            logger.info(
                "Retroactive article_pair: removed article %s from story %s (pair %s, %s)",
                remove_id[:12],
                str(story_id)[:8],
                a[:12],
                b[:12],
            )
            recompute_story_centroid(story_id)
            stories_db.set_story_needs_rewrite(story_id, True)
            removed += 1

    return removed
