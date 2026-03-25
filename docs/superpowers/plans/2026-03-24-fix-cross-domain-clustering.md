# Fix Cross-Domain Clustering Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent sports articles from clustering with international/politics articles by adding a source-topic hard gate and enriching embedding text with domain context.

**Architecture:** Three layered improvements — (1) raise the cosine similarity threshold from the broken 0.80 back to the documented range, (2) inject a domain-topic compatibility check into both clustering paths so domain-exclusive sources with disjoint topic sets never merge, (3) prepend topic/category labels to embedding text so the vector space itself becomes more domain-aware, requiring a one-time re-embedding migration.

**Tech Stack:** Python 3.12, Flask, PostgreSQL 18, Ollama (nomic-embed-text, 768-dim), Alembic migrations, pytest.

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `config/app.yaml` | Modify | Raise `story_similarity_threshold` 0.80 → 0.92 |
| `app/config.py` | Modify | Update `DEFAULTS["story_similarity_threshold"]` to match |
| `app/clustering/service.py` | Modify | Add topic gate functions; thread into both clustering paths; enrich embedding text |
| `alembic/versions/027_reset_embeddings_for_topic_enrichment.py` | Create | Reset embeddings to NULL so they are re-generated with the new text format |
| `tests/test_clustering_service.py` | Create | Unit tests for `_topics_compatible`, `_build_source_topics_index`, and `_text_to_embed` |

---

## Task 1: Raise the Similarity Threshold

**Files:**
- Modify: `config/app.yaml:112`
- Modify: `app/config.py:67`

- [ ] **Step 1: Change threshold in app.yaml**

```yaml
# config/app.yaml line 112
story_similarity_threshold: 0.92
```

- [ ] **Step 2: Change threshold default in app/config.py**

At line 67 inside `DEFAULTS`:
```python
"story_similarity_threshold": 0.92,
```

- [ ] **Step 3: Verify no tests break**

```bash
pytest tests/ -x -q
```
Expected: all pass (this is a pure config change).

- [ ] **Step 4: Commit**

```bash
git add config/app.yaml app/config.py
git commit -m "fix(clustering): raise similarity threshold from 0.80 to 0.92"
```

---

## Task 2: Unit Tests for Topic Gate (write tests first — TDD)

**Files:**
- Create: `tests/test_clustering_service.py`

These tests exercise pure functions that don't touch the DB or Ollama. They must pass before any implementation.

- [ ] **Step 1: Create the test file**

```python
# tests/test_clustering_service.py
"""Unit tests for topic-gate and embedding-text helpers in clustering service."""

import pytest

from app.clustering.service import _topics_compatible, _text_to_embed


# --- _topics_compatible ---

def _t(topics_a: list[str], topics_b: list[str], known: dict | None = None) -> bool:
    """Helper: build minimal source_topics and call _topics_compatible."""
    source_topics = {"src_a": frozenset(topics_a), "src_b": frozenset(topics_b)}
    if known:
        source_topics.update({k: frozenset(v) for k, v in known.items()})
    return _topics_compatible("src_a", "src_b", source_topics)


def test_sports_vs_politics_blocked() -> None:
    assert _t(["sports"], ["politics", "society"]) is False


def test_sports_vs_international_blocked() -> None:
    assert _t(["sports"], ["international"]) is False


def test_same_domain_allowed() -> None:
    assert _t(["sports"], ["sports"]) is True


def test_overlapping_domains_allowed() -> None:
    assert _t(["politics", "society"], ["politics", "economy"]) is True


def test_general_source_always_compatible_with_sports() -> None:
    assert _t(["general"], ["sports"]) is True


def test_general_source_always_compatible_with_politics() -> None:
    assert _t(["politics", "society"], ["general", "politics"]) is True


def test_unknown_source_permissive() -> None:
    """Sources not in index default to compatible."""
    source_topics: dict[str, frozenset[str]] = {"src_a": frozenset(["sports"])}
    assert _topics_compatible("src_a", "unknown_src", source_topics) is True


def test_both_unknown_permissive() -> None:
    assert _topics_compatible("x", "y", {}) is True


# --- _text_to_embed ---

def _make_article(
    title: str = "Title",
    full_text: str = "",
    raw_text: str = "",
    categories: list | None = None,
    source_topics: list | None = None,
) -> dict:
    return {
        "title": title,
        "full_text": full_text,
        "raw_text": raw_text,
        "categories": categories or [],
        "_source_topics": source_topics or [],
    }


def test_text_to_embed_no_context_is_plain() -> None:
    art = _make_article(title="Headline", full_text="Body text.")
    result = _text_to_embed(art)
    assert result == "Headline Body text."


def test_text_to_embed_prepends_source_topics() -> None:
    art = _make_article(title="Match result", source_topics=["sports"])
    result = _text_to_embed(art)
    assert result.startswith("topics: sports.")


def test_text_to_embed_prepends_categories() -> None:
    art = _make_article(title="Match result", categories=["Football", "La Liga"])
    result = _text_to_embed(art)
    assert "categories: Football, La Liga" in result


def test_text_to_embed_topics_and_categories() -> None:
    art = _make_article(
        title="Transfer news",
        source_topics=["sports"],
        categories=["Football"],
    )
    result = _text_to_embed(art)
    assert result.startswith("topics: sports. categories: Football.")


def test_text_to_embed_content_truncated_at_2000() -> None:
    art = _make_article(title="T", full_text="x" * 3000)
    result = _text_to_embed(art)
    # "T" (1) + " " (1) + "x" * 2000 = 2002 chars; no prefix because no topics/categories
    assert len(result) == 2002


def test_text_to_embed_falls_back_to_raw_text() -> None:
    art = _make_article(title="T", raw_text="raw content")
    result = _text_to_embed(art)
    assert "raw content" in result


def test_text_to_embed_empty_categories_ignored() -> None:
    art = _make_article(title="T", categories=["", "  ", None])
    result = _text_to_embed(art)
    assert "categories" not in result
```

- [ ] **Step 2: Run tests — all must FAIL (functions not yet updated)**

```bash
pytest tests/test_clustering_service.py -v
```
Expected: ImportError or multiple FAILs. This confirms TDD baseline.

---

## Task 3: Implement `_topics_compatible` and `_build_source_topics_index`

**Files:**
- Modify: `app/clustering/service.py`

- [ ] **Step 1: Add `_build_source_topics_index` after `_load_exclusion_rules` (~line 100)**

```python
def _build_source_topics_index() -> dict[str, frozenset[str]]:
    """Return mapping source_id -> frozenset of topics, loaded from sources.yaml.

    Loaded once per cluster run. Used for the domain-compatibility gate.
    A source not found in the index is treated as general-capable (permissive default).
    """
    from app.config import load_sources

    index: dict[str, frozenset[str]] = {}
    for src in load_sources():
        sid = src.get("id")
        topics = src.get("topics") or []
        if sid and isinstance(topics, list):
            index[sid] = frozenset(str(t) for t in topics)
    return index
```

- [ ] **Step 2: Add `_topics_compatible` immediately after**

```python
def _topics_compatible(
    source_id_a: str,
    source_id_b: str,
    source_topics: dict[str, frozenset[str]],
) -> bool:
    """Return False only if both sources are domain-exclusive with disjoint topic sets.

    A source is "domain-exclusive" if its topic set does not include "general".
    General-capable sources can always cluster with any other source.
    """
    topics_a = source_topics.get(source_id_a)
    topics_b = source_topics.get(source_id_b)
    if topics_a is None or topics_b is None:
        return True  # unknown source: permissive default
    if "general" in topics_a or "general" in topics_b:
        return True  # at least one general-capable source: always allow
    return bool(topics_a & topics_b)  # both exclusive: require non-empty intersection
```

- [ ] **Step 3: Run topic-gate tests — they must now pass**

```bash
pytest tests/test_clustering_service.py -k "compatible" -v
```
Expected: all `test_*compatible*` and `test_*unknown*` tests PASS.

---

## Task 4: Enrich `_text_to_embed` with Topic/Category Prefix

**Files:**
- Modify: `app/clustering/service.py` (`_text_to_embed` function, lines ~124–131)

- [ ] **Step 1: Replace `_text_to_embed`**

```python
def _text_to_embed(article: dict[str, Any]) -> str:
    """Build text for embedding: domain prefix + title + content excerpt.

    The caller may inject '_source_topics' (list[str]) as a synthetic key on the
    article dict before calling. This key is never persisted to the database.
    """
    title = (article.get("title") or "").strip()
    full = (article.get("full_text") or "").strip()
    raw = (article.get("raw_text") or "").strip()
    content = (full or raw)[:2000]

    src_topics: list[str] = article.get("_source_topics") or []
    rss_cats: list[str] = [
        str(c).strip()
        for c in (article.get("categories") or [])
        if c and str(c).strip()
    ][:5]

    parts: list[str] = []
    if src_topics:
        parts.append("topics: " + ", ".join(sorted(src_topics)))
    if rss_cats:
        parts.append("categories: " + ", ".join(rss_cats))
    prefix = ". ".join(parts) + ". " if parts else ""

    return (prefix + title + " " + content).strip()
```

- [ ] **Step 2: Run embedding text tests**

```bash
pytest tests/test_clustering_service.py -k "embed" -v
```
Expected: all `test_text_to_embed_*` tests PASS.

---

## Task 5: Thread Topic Gate into `_cluster_articles`

**Files:**
- Modify: `app/clustering/service.py` (`_cluster_articles` function, lines ~183–256)

- [ ] **Step 1: Add `source_topics` parameter to `_cluster_articles`**

Change the signature from:
```python
def _cluster_articles(
    articles: list[dict[str, Any]],
    threshold: float,
    rules: ExclusionRules,
) -> list[list[str]]:
```
To:
```python
def _cluster_articles(
    articles: list[dict[str, Any]],
    threshold: float,
    rules: ExclusionRules,
    source_topics: dict[str, frozenset[str]],
) -> list[list[str]]:
```

- [ ] **Step 2: Add topic check inside the `for a in g1: for b in g2:` loop**

After the existing `if rules.article_pairs and _article_pair_blocked(...)` block (around line 234), add:

```python
sa = art_a.get("source_id") or ""
sb = art_b.get("source_id") or ""
if sa and sb and not _topics_compatible(sa, sb, source_topics):
    cross_ok = False
    break
```

The full inner loop becomes (in order): article_pair_blocked check → topic_compatible check → effective threshold check.

- [ ] **Step 3: Run full test suite**

```bash
pytest tests/ -x -q
```
Expected: all pass. (The call site in `run_cluster_and_embed` will be updated in Task 6.)

---

## Task 6: Thread Topic Gate into `_assign_to_existing_stories` and Wire Up

**Files:**
- Modify: `app/clustering/service.py` (`_assign_to_existing_stories` and `run_cluster_and_embed`)

- [ ] **Step 1: Add parameters to `_assign_to_existing_stories`**

Change signature from:
```python
def _assign_to_existing_stories(
    articles: list[dict[str, Any]],
    existing_stories: list[dict[str, Any]],
    threshold: float,
    story_member_ids: dict[str, list[str]],
    rules: ExclusionRules,
) -> tuple[list[tuple[str, str]], list[dict[str, Any]]]:
```
To:
```python
def _assign_to_existing_stories(
    articles: list[dict[str, Any]],
    existing_stories: list[dict[str, Any]],
    threshold: float,
    story_member_ids: dict[str, list[str]],
    rules: ExclusionRules,
    source_topics: dict[str, frozenset[str]],
    story_source_ids: dict[str, set[str]],
) -> tuple[list[tuple[str, str]], list[dict[str, Any]]]:
```

- [ ] **Step 2: Add topic check in the inner loop over stories**

Inside `for sid, centroid in story_centroids.items():`, after the existing blocked check (around line 170), add:

```python
art_src = (art.get("source_id") or "").strip()
if art_src:
    story_srcs = story_source_ids.get(sid, set())
    if story_srcs and not any(
        _topics_compatible(art_src, s, source_topics) for s in story_srcs
    ):
        continue
```

- [ ] **Step 3: Update `run_cluster_and_embed` to build and pass new arguments**

After the existing `exclusion_rules = _load_exclusion_rules()` line, add:
```python
source_topics = _build_source_topics_index()
```

When building `story_member_ids` (around line 353), also build `story_source_ids`:
```python
story_member_ids: dict[str, list[str]] = {}
story_source_ids: dict[str, set[str]] = {}
for row in existing:
    sid = row["story_id"]
    members = db_stories.get_articles_in_story(sid)
    story_member_ids[sid] = [a["id"] for a in members]
    story_source_ids[sid] = {a["source_id"] for a in members if a.get("source_id")}
```

Update the call to `_assign_to_existing_stories`:
```python
assigned, to_cluster = _assign_to_existing_stories(
    to_cluster, existing, threshold, story_member_ids, exclusion_rules,
    source_topics, story_source_ids,
)
```

Update the call to `_cluster_articles`:
```python
groups = _cluster_articles(to_cluster, threshold, exclusion_rules, source_topics) if to_cluster else []
```

Also inject `_source_topics` **inside** the existing `for i, article in enumerate(to_embed):` loop body, **before** the `_text_to_embed(article)` call (around line 297). The injection must happen before `_text_to_embed` is invoked — a separate preceding loop would be too late because the text is extracted immediately inside the same loop:

```python
# Inside the existing loop — replace the loop body:
for i, article in enumerate(to_embed):
    src_topics = list(source_topics.get(article.get("source_id") or "", frozenset()))
    article["_source_topics"] = src_topics      # inject before text extraction
    text = _text_to_embed(article)
    if text:
        eligible.append((i, article, text))
```

- [ ] **Step 4: Run full test suite**

```bash
pytest tests/ -x -q
```
Expected: all pass.

- [ ] **Step 5: Commit Phases 2 + 3 logic**

```bash
git add app/clustering/service.py tests/test_clustering_service.py
git commit -m "feat(clustering): add source-topic hard gate and topic-enriched embeddings"
```

---

## Task 7: Migration to Reset Embeddings

**Files:**
- Create: `alembic/versions/027_reset_embeddings_for_topic_enrichment.py`

Existing embeddings were computed without the domain prefix. Reset them to NULL so the next
cluster run re-embeds with the new enriched text.

- [ ] **Step 1: Create the migration file**

```python
"""Reset article embeddings to trigger re-embedding with topic-enriched text.

Revision ID: c1d2e3f4a5b7
Revises: b2c3d4e5f6a1
Create Date: 2026-03-24
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c1d2e3f4a5b7"
down_revision: str | None = "b2c3d4e5f6a1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Only reset news articles — non-news articles are never embedded.
    op.execute("UPDATE articles SET embedding = NULL WHERE article_type = 'news'")
    # Reset story centroids — they will be recomputed after re-embedding.
    op.execute("UPDATE stories SET centroid_embedding = NULL")


def downgrade() -> None:
    # Embeddings cannot be restored from migration; intentional no-op.
    pass
```

- [ ] **Step 2: Verify migration chains correctly**

```bash
alembic history | head -5
```
Expected: `027_reset_embeddings_for_topic_enrichment` appears after `026_add_article_type`.

- [ ] **Step 3: Run full test suite**

```bash
pytest tests/ -x -q
```
Expected: all pass.

- [ ] **Step 4: Commit migration**

```bash
git add alembic/versions/027_reset_embeddings_for_topic_enrichment.py
git commit -m "feat(clustering): migration 027 — reset embeddings for topic-enriched re-embedding"
```

---

## Verification

After deploying to a running instance:

1. **Apply migration:**
   ```bash
   flask db upgrade
   ```

2. **Trigger cluster job** (or wait for scheduler):
   ```bash
   flask cluster-articles
   ```

3. **Check cross-domain story contamination** (should return 0 rows):
   ```sql
   SELECT s.id, array_agg(DISTINCT a.source_id) AS sources
   FROM stories s
   JOIN story_articles sa ON sa.story_id = s.id
   JOIN articles a ON a.id = sa.article_id
   GROUP BY s.id
   HAVING bool_or(a.source_id IN ('marca','diario_as','mundodeportivo','sport'))
      AND bool_or(a.source_id NOT IN ('marca','diario_as','mundodeportivo','sport'));
   ```

4. **Check re-embedding is complete** (should return 0 after cluster run):
   ```sql
   SELECT count(*) FROM articles WHERE embedding IS NULL AND article_type = 'news';
   ```

5. **Spot-check ops dashboard:** open a few stories from sports sources and confirm no political/international articles appear.
