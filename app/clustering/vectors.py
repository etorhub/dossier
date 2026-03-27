"""Embedding vectors and centroids: pure math + DB only.

Used from ops (slim web image) and worker. Do not import LLM, httpx, or embeddings
providers here — those are not installed in the web/ops container.
"""

from __future__ import annotations

import json
from typing import Any, cast

from app.db import stories as db_stories


def embedding_from_article(article: dict[str, Any]) -> list[float] | None:
    """Extract embedding from article row. Returns None if invalid."""
    emb = article.get("embedding")
    if emb is None:
        return None
    if isinstance(emb, list):
        if len(emb) == 0:
            return None
        return emb
    if isinstance(emb, str):
        try:
            return cast(list[float], json.loads(emb))
        except json.JSONDecodeError:
            return None
    return None


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity between two vectors."""
    if len(a) != len(b) or len(a) == 0:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return float(dot / (norm_a * norm_b))


def compute_centroid(embeddings: list[list[float]]) -> list[float] | None:
    """Compute mean of embeddings. Returns None if empty or invalid."""
    valid = [e for e in embeddings if e and len(e) > 0]
    if not valid or not all(len(emb) == len(valid[0]) for emb in valid):
        return None
    n = len(valid)
    dim = len(valid[0])
    return [sum(emb[i] for emb in valid) / n for i in range(dim)]


def recompute_story_centroid(story_id: str) -> None:
    """Recompute and store story centroid from member articles, or clear if empty."""
    articles = db_stories.get_articles_in_story(story_id)
    embeddings_raw = [embedding_from_article(a) for a in articles]
    embeddings: list[list[float]] = [e for e in embeddings_raw if e is not None]
    if embeddings:
        centroid = compute_centroid(embeddings)
        if centroid:
            db_stories.update_story_centroid(story_id, centroid)
    else:
        db_stories.clear_story_centroid(story_id)
