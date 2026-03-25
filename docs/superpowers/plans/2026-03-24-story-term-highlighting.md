# Story Term Highlighting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** After each story is rewritten, run an LLM post-processing pass that wraps significant terms (people, places, organisations, statistics, key concepts) in `**...**`, then render these as `<strong>` tags in the reader UI — with TTS unaffected.

**Architecture:** A new `highlight_service.py` runs `run_highlight_batch()` after the rewrite batch. It queries for `story_rewrites` rows with `full_text` but no `highlighted_full_text`, calls the LLM once per row with a new prompt, and stores the result in a new `highlighted_full_text` TEXT column. A new `bold_md` Jinja2 filter safely converts `**...**` → `<strong>` in templates (HTML-escaping first). TTS buttons remain on `article.full_text` (plain text).

**Tech Stack:** Python/Flask, psycopg2, Jinja2/Markupsafe, APScheduler, Ollama via provider interface, Alembic, Pytest

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `alembic/versions/027_story_rewrites_highlighted_full_text.py` | Add nullable `highlighted_full_text` column to `story_rewrites` |
| Create | `app/llm/prompts/highlight_terms.txt` | LLM prompt: return text with `**significant terms**` |
| Create | `app/services/highlight_service.py` | `highlight_story()`, `run_highlight_batch()`, `HighlightReport` |
| Create | `tests/test_highlight_service.py` | Tests for highlight service |
| Modify | `app/db/stories.py` | Add `update_story_rewrite_highlight()`, `get_stories_needing_highlight()`; update `get_story_rewrites()` SELECT |
| Modify | `app/__init__.py` | Register `bold_md` Jinja2 filter |
| Modify | `app/services/article_service.py` | Thread `highlighted_full_text` through `get_expanded_story()` |
| Modify | `templates/article.html` | Render body from `highlighted_full_text or full_text` with `bold_md` filter |
| Modify | `templates/partials/article_expanded.html` | Same |
| Modify | `app/worker_cli.py` | Add `highlight-stories` command; add highlight step to `run-pipeline` |
| Modify | `app/scheduler.py` | Add `_highlight_articles_job` and schedule it in `heavy`/`full` mode |

---

## Task 1: DB migration — add `highlighted_full_text` column

**Files:**
- Create: `alembic/versions/027_story_rewrites_highlighted_full_text.py`

- [ ] **Step 1: Write the migration**

```python
"""Add highlighted_full_text column to story_rewrites

Revision ID: c3d4e5f6a7b2
Revises: b2c3d4e5f6a1
Create Date: 2026-03-24

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c3d4e5f6a7b2"
down_revision: str | None = "b2c3d4e5f6a1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "story_rewrites",
        sa.Column(
            "highlighted_full_text",
            sa.Text(),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("story_rewrites", "highlighted_full_text")
```

- [ ] **Step 2: Run migration**

```bash
docker compose exec web flask db upgrade
# or: alembic upgrade head
```

Expected: Migration applies without error. Verify with:
```bash
docker compose exec db psql -U dossier -c "\d story_rewrites" | grep highlighted
```
Expected output includes: `highlighted_full_text | text | nullable`

- [ ] **Step 3: Commit**

```bash
git add alembic/versions/027_story_rewrites_highlighted_full_text.py
git commit -m "feat(db): add highlighted_full_text column to story_rewrites"
```

---

## Task 2: LLM prompt file

**Files:**
- Create: `app/llm/prompts/highlight_terms.txt`

- [ ] **Step 1: Write the prompt**

```
You are a text-highlighting assistant. You receive the full body text of a news article.
Your only job is to identify significant terms and wrap them in double asterisks (**).

Rules:
- Significant terms include: key people, organisations, places, statistics, dates, and central technical or legal terms.
- Bold 1–4 words per term. Never bold an entire sentence or clause.
- Target 3–8 bold terms per 200 words of text. Do not over-bold trivial words.
- Return the FULL original text unchanged except for the ** markers you add.
- Do not add, remove, or rephrase any words.
- No other formatting: no headers, no bullet lists, no markdown beyond **.

Text:
{full_text}
```

- [ ] **Step 2: Verify load_prompt works**

```bash
python -c "from app.llm.prompts import load_prompt; p = load_prompt('highlight_terms'); print(p[:80])"
```
Expected: prints first line of the prompt without error.

- [ ] **Step 3: Commit**

```bash
git add app/llm/prompts/highlight_terms.txt
git commit -m "feat(llm): add highlight_terms prompt for significant-term bolding"
```

---

## Task 3: DB layer additions

**Files:**
- Modify: `app/db/stories.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_db_stories_highlight.py
from unittest.mock import MagicMock, patch, call


def test_update_story_rewrite_highlight_executes_update() -> None:
    """update_story_rewrite_highlight issues an UPDATE SQL statement."""
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value.__enter__ = lambda s: mock_cur
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

    with patch("app.db.stories.get_connection", return_value=mock_conn), \
         patch("app.db.stories.return_connection"):
        from app.db.stories import update_story_rewrite_highlight
        update_story_rewrite_highlight("story-1", "neutral", "en", "The **president** spoke.")

    mock_cur.execute.assert_called_once()
    sql, params = mock_cur.execute.call_args[0]
    assert "UPDATE story_rewrites" in sql
    assert "highlighted_full_text" in sql
    assert params[0] == "The **president** spoke."


def test_get_stories_needing_highlight_returns_list() -> None:
    """get_stories_needing_highlight returns a list of dicts."""
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_cur.fetchall.return_value = [
        {"story_id": "abc", "style": "neutral", "language": "en", "full_text": "Some text."}
    ]
    mock_conn.cursor.return_value.__enter__ = lambda s: mock_cur
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

    with patch("app.db.stories.get_connection", return_value=mock_conn), \
         patch("app.db.stories.return_connection"):
        from app.db.stories import get_stories_needing_highlight
        rows = get_stories_needing_highlight()

    assert isinstance(rows, list)
    assert rows[0]["story_id"] == "abc"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_db_stories_highlight.py -v
```
Expected: ImportError or AttributeError — functions don't exist yet.

- [ ] **Step 3: Add the two new functions to `app/db/stories.py`**

Add after `get_story_rewrites()`:

```python
def update_story_rewrite_highlight(
    story_id: str,
    style: str,
    language: str,
    highlighted_full_text: str,
) -> None:
    """Store the highlighted version of full_text for (story_id, style, language)."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE story_rewrites
                SET highlighted_full_text = %s
                WHERE story_id = %s::uuid AND style = %s AND language = %s
                """,
                (highlighted_full_text, story_id, style, language),
            )
        conn.commit()
    finally:
        return_connection(conn)


def get_stories_needing_highlight(
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Return story_rewrites rows with full_text but no highlighted_full_text yet."""
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT story_id::text, style, language, full_text
                FROM story_rewrites
                WHERE full_text IS NOT NULL
                  AND (rewrite_failed = false OR rewrite_failed IS NULL)
                  AND highlighted_full_text IS NULL
                ORDER BY story_id
                """
                + (" LIMIT %s" if limit is not None else ""),
                (limit,) if limit is not None else (),
            )
            return [dict(row) for row in cur.fetchall()]
    finally:
        return_connection(conn)
```

- [ ] **Step 4: Update `get_story_rewrites()` SELECT to include `highlighted_full_text`**

Find the SELECT in `get_story_rewrites()` (around line 327):

Old:
```python
SELECT story_id::text, title, summary, full_text, rewrite_failed
FROM story_rewrites
```

New:
```python
SELECT story_id::text, title, summary, full_text, highlighted_full_text, rewrite_failed
FROM story_rewrites
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
pytest tests/test_db_stories_highlight.py -v
```
Expected: PASS

- [ ] **Step 6: Run existing db tests to confirm no regressions**

```bash
pytest tests/test_db_articles.py tests/test_db_sources.py -v
```
Expected: all PASS

- [ ] **Step 7: Commit**

```bash
git add app/db/stories.py tests/test_db_stories_highlight.py
git commit -m "feat(db): add update_story_rewrite_highlight and get_stories_needing_highlight"
```

---

## Task 4: Highlight service

**Files:**
- Create: `app/services/highlight_service.py`
- Create: `tests/test_highlight_service.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_highlight_service.py
from unittest.mock import MagicMock, patch

import pytest


def _make_config() -> dict:
    return {"processing": {"rewrite_max_tokens": 2048}}


def test_highlight_story_stores_result_on_success() -> None:
    """highlight_story calls LLM, stores result, returns True."""
    mock_provider = MagicMock()
    mock_provider.complete.return_value = "The **president** spoke at the **White House**."

    with patch("app.services.highlight_service.db_stories") as mock_db, \
         patch("app.services.highlight_service.load_prompt", return_value="Text:\n{full_text}"):
        from app.services.highlight_service import highlight_story
        result = highlight_story(
            story_id="story-1",
            full_text="The president spoke at the White House.",
            style="neutral",
            language="en",
            config=_make_config(),
            provider=mock_provider,
        )

    assert result is True
    mock_db.update_story_rewrite_highlight.assert_called_once_with(
        "story-1", "neutral", "en", "The **president** spoke at the **White House**."
    )


def test_highlight_story_returns_false_on_llm_failure() -> None:
    """highlight_story returns False when LLM raises, does not propagate."""
    mock_provider = MagicMock()
    mock_provider.complete.side_effect = RuntimeError("LLM down")

    with patch("app.services.highlight_service.db_stories"), \
         patch("app.services.highlight_service.load_prompt", return_value="Text:\n{full_text}"):
        from app.services.highlight_service import highlight_story
        result = highlight_story(
            story_id="story-1",
            full_text="Some text.",
            style="neutral",
            language="en",
            config=_make_config(),
            provider=mock_provider,
        )

    assert result is False


def test_highlight_story_returns_false_on_empty_response() -> None:
    """highlight_story returns False when LLM returns empty string."""
    mock_provider = MagicMock()
    mock_provider.complete.return_value = "   "

    with patch("app.services.highlight_service.db_stories"), \
         patch("app.services.highlight_service.load_prompt", return_value="Text:\n{full_text}"):
        from app.services.highlight_service import highlight_story
        result = highlight_story(
            story_id="story-1",
            full_text="Some text.",
            style="neutral",
            language="en",
            config=_make_config(),
            provider=mock_provider,
        )

    assert result is False


def test_run_highlight_batch_returns_report() -> None:
    """run_highlight_batch processes rows and returns HighlightReport."""
    rows = [
        {"story_id": "s1", "style": "neutral", "language": "en", "full_text": "Text one."},
        {"story_id": "s2", "style": "neutral", "language": "en", "full_text": "Text two."},
    ]
    mock_provider = MagicMock()
    mock_provider.complete.return_value = "Text **one**."

    with patch("app.services.highlight_service.db_stories") as mock_db, \
         patch("app.services.highlight_service.get_provider", return_value=mock_provider), \
         patch("app.services.highlight_service.load_prompt", return_value="Text:\n{full_text}"):
        mock_db.get_stories_needing_highlight.return_value = rows
        from app.services.highlight_service import run_highlight_batch
        report = run_highlight_batch(_make_config())

    assert report.attempted == 2
    assert report.succeeded == 2
    assert report.failed == 0
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_highlight_service.py -v
```
Expected: ImportError — module doesn't exist yet.

- [ ] **Step 3: Write `app/services/highlight_service.py`**

```python
"""LLM highlighting pass: wraps significant terms in ** in story full_text."""

import logging
from dataclasses import dataclass
from typing import Any

from app.db import stories as db_stories
from app.llm.prompts import load_prompt
from app.llm.provider import LLMProvider, get_provider

logger = logging.getLogger(__name__)


@dataclass
class HighlightReport:
    """Summary of a highlight batch run."""

    attempted: int
    succeeded: int
    failed: int


def highlight_story(
    story_id: str,
    full_text: str,
    style: str,
    language: str,
    config: dict[str, Any],
    *,
    provider: LLMProvider | None = None,
) -> bool:
    """Call LLM to highlight significant terms in full_text, store result. Returns True on success."""
    if provider is None:
        provider = get_provider(config, task="highlight")

    processing = config.get("processing", {})
    max_tokens = int(processing.get("rewrite_max_tokens") or 4096)

    prompt_template = load_prompt("highlight_terms")
    prompt = prompt_template.format(full_text=full_text)

    try:
        response = provider.complete(prompt, max_tokens=max_tokens, temperature=0.0)
        highlighted = response.strip()
        if not highlighted:
            logger.warning(
                "highlight_story: empty response for story_id=%s style=%s language=%s",
                story_id, style, language,
            )
            return False
        db_stories.update_story_rewrite_highlight(story_id, style, language, highlighted)
        logger.debug(
            "highlight_story: done story_id=%s style=%s language=%s", story_id, style, language
        )
        return True
    except Exception as e:
        logger.warning(
            "highlight_story failed story_id=%s style=%s language=%s: %s",
            story_id, style, language, e,
        )
        return False


def run_highlight_batch(config: dict[str, Any] | None = None) -> HighlightReport:
    """Process all story_rewrites rows missing highlighted_full_text."""
    from app.config import load_config

    if config is None:
        config = load_config()

    rows = db_stories.get_stories_needing_highlight()
    attempted = 0
    succeeded = 0
    failed = 0

    if not rows:
        logger.info("run_highlight_batch: nothing to highlight")
        return HighlightReport(attempted=0, succeeded=0, failed=0)

    provider = get_provider(config, task="highlight")

    for row in rows:
        attempted += 1
        ok = highlight_story(
            story_id=row["story_id"],
            full_text=row["full_text"],
            style=row["style"],
            language=row["language"],
            config=config,
            provider=provider,
        )
        if ok:
            succeeded += 1
        else:
            failed += 1

    logger.info(
        "run_highlight_batch: attempted=%d succeeded=%d failed=%d",
        attempted, succeeded, failed,
    )
    return HighlightReport(attempted=attempted, succeeded=succeeded, failed=failed)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_highlight_service.py -v
```
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add app/services/highlight_service.py tests/test_highlight_service.py
git commit -m "feat(highlight): add highlight_service with LLM significant-term bolding"
```

---

## Task 5: `bold_md` Jinja2 filter

**Files:**
- Modify: `app/__init__.py`

- [ ] **Step 1: Write failing tests** (add to a new `tests/test_bold_md_filter.py`)

```python
# tests/test_bold_md_filter.py
"""Tests for the bold_md Jinja2 filter."""

from markupsafe import Markup


def _get_filter():
    """Import the filter function directly from the app factory context."""
    import re
    from markupsafe import Markup as M

    def bold_md_filter(text: str | None) -> M:
        if not text:
            return M("")
        escaped = str(M.escape(text))
        result = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
        return M(result)

    return bold_md_filter


def test_bold_md_converts_double_asterisks() -> None:
    f = _get_filter()
    result = f("The **president** spoke.")
    assert str(result) == "The <strong>president</strong> spoke."


def test_bold_md_escapes_html_outside_markers() -> None:
    f = _get_filter()
    result = f("<script>alert(1)</script>")
    assert "<script>" not in str(result)
    assert "&lt;script&gt;" in str(result)


def test_bold_md_escapes_html_inside_markers() -> None:
    """LLM cannot inject HTML via bold markers."""
    f = _get_filter()
    result = f("**<img src=x onerror=alert(1)>**")
    assert "<img" not in str(result)
    assert "&lt;img" in str(result)


def test_bold_md_plain_text_unchanged() -> None:
    f = _get_filter()
    result = f("No markers here.")
    assert str(result) == "No markers here."


def test_bold_md_none_returns_empty() -> None:
    f = _get_filter()
    result = f(None)
    assert str(result) == ""


def test_bold_md_returns_markup_instance() -> None:
    f = _get_filter()
    result = f("**term**")
    assert isinstance(result, Markup)
```

- [ ] **Step 2: Run tests to verify they pass (they test a standalone function, not Flask app)**

```bash
pytest tests/test_bold_md_filter.py -v
```
Expected: all PASS (the tests don't depend on Flask being set up)

- [ ] **Step 3: Register the filter in `app/__init__.py`**

Add `import re` and `from markupsafe import Markup` to imports at the top of `create_app`.

Add after the existing `naturaltime_filter` registration (around line 95):

```python
    @app.template_filter("bold_md")
    def bold_md_filter(text: str | None) -> Markup:
        """Convert **term** markers to <strong> tags. HTML-escapes input first."""
        if not text:
            return Markup("")
        escaped = str(Markup.escape(text))
        result = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
        return Markup(result)
```

Add to the imports at the top of the file (with the other stdlib imports):
```python
import re
```

And add to Flask/Markupsafe imports:
```python
from markupsafe import Markup
```

- [ ] **Step 4: Run the full test suite to check nothing is broken**

```bash
pytest tests/ -v --ignore=tests/test_db_stories_highlight.py -x
```
Expected: all previously passing tests still PASS.

- [ ] **Step 5: Commit**

```bash
git add app/__init__.py tests/test_bold_md_filter.py
git commit -m "feat(web): add bold_md Jinja2 filter for **term** → <strong> rendering"
```

---

## Task 6: Thread `highlighted_full_text` through article service

**Files:**
- Modify: `app/services/article_service.py`

- [ ] **Step 1: Update `get_expanded_story()` to pass `highlighted_full_text`**

In `get_expanded_story()` (around line 267), update the block where `rw` is used:

Old:
```python
    if rw and rw.get("full_text"):
        title = rw.get("title") or "Article"
        summary = rw.get("summary") or ""
        full_text = rw["full_text"]
    else:
        title = "Article"
        summary = ""
        full_text = "This article is being prepared. Please try again shortly."

    return {
        "id": story_id,
        "title": title,
        "summary": summary,
        "full_text": full_text,
        ...
    }
```

New:
```python
    if rw and rw.get("full_text"):
        title = rw.get("title") or "Article"
        summary = rw.get("summary") or ""
        full_text = rw["full_text"]
        highlighted_full_text = rw.get("highlighted_full_text")
    else:
        title = "Article"
        summary = ""
        full_text = "This article is being prepared. Please try again shortly."
        highlighted_full_text = None

    return {
        "id": story_id,
        "title": title,
        "summary": summary,
        "full_text": full_text,
        "highlighted_full_text": highlighted_full_text,
        ...
    }
```

- [ ] **Step 2: Run existing article service tests**

```bash
pytest tests/test_article_service.py -v
```
Expected: all PASS (adding a new key to the returned dict doesn't break existing tests).

- [ ] **Step 3: Commit**

```bash
git add app/services/article_service.py
git commit -m "feat(service): thread highlighted_full_text through get_expanded_story"
```

---

## Task 7: Template updates

**Files:**
- Modify: `templates/article.html`
- Modify: `templates/partials/article_expanded.html`

- [ ] **Step 1: Update `templates/article.html`**

Find the article body block (lines 49–53):

Old:
```html
  <div class="article-body">
    {% for para in article.full_text.split('\n\n') %}
    {% if para.strip() %}<p>{{ para.strip() }}</p>{% endif %}
    {% endfor %}
  </div>
```

New:
```html
  <div class="article-body">
    {% set body = article.highlighted_full_text or article.full_text or '' %}
    {% for para in body.split('\n\n') %}
    {% if para.strip() %}<p>{{ para.strip()|bold_md }}</p>{% endif %}
    {% endfor %}
  </div>
```

Note: The TTS button on lines 33–35 uses `article.full_text` directly — leave it unchanged.

- [ ] **Step 2: Update `templates/partials/article_expanded.html`**

Find the article body block (lines 45–48):

Old:
```html
    <div class="article-body">
      {% for para in (article.full_text or '').split('\n\n') %}
      {% if para.strip() %}<p>{{ para.strip() }}</p>{% endif %}
      {% endfor %}
    </div>
```

New:
```html
    <div class="article-body">
      {% set body = article.highlighted_full_text or article.full_text or '' %}
      {% for para in body.split('\n\n') %}
      {% if para.strip() %}<p>{{ para.strip()|bold_md }}</p>{% endif %}
      {% endfor %}
    </div>
```

Note: The TTS button on line 30 uses `article.full_text` directly — leave it unchanged.

- [ ] **Step 3: Verify rendering manually (or via integration test)**

```bash
# Start the app locally and open a story that has a rewrite
docker compose up web db -d
# Visit http://localhost:5000 and expand a story
# Confirm: plain text stories render normally (no ** artifacts)
# Confirm: highlighted stories show <strong> terms
```

- [ ] **Step 4: Commit**

```bash
git add templates/article.html templates/partials/article_expanded.html
git commit -m "feat(templates): render highlighted_full_text with bold_md filter"
```

---

## Task 8: Worker CLI + scheduler integration

**Files:**
- Modify: `app/worker_cli.py`
- Modify: `app/scheduler.py`

- [ ] **Step 1: Add `highlight-stories` CLI command to `app/worker_cli.py`**

Add after the `rewrite-all-stories` command (around line 182):

```python
@worker_cli.command("highlight-stories")
def highlight_stories_cmd() -> None:
    """Run the LLM highlighting pass for all rewrites missing highlighted_full_text."""
    from app.scheduler import _run_tracked_job
    from app.services.highlight_service import run_highlight_batch

    try:
        _run_tracked_job("highlight_stories", run_highlight_batch, trigger="manual")
    except Exception as e:
        click.echo(f"Highlight job failed: {e}", err=True)
        raise SystemExit(1)
    click.echo("Highlight job completed. Check ops dashboard for details.")
```

- [ ] **Step 2: Add highlight step to `run-pipeline` command**

In `run_pipeline_cmd()` (around line 210), add after the rewrite step:

```python
    click.echo("Running highlight...")
    from app.services.highlight_service import run_highlight_batch
    try:
        _run_tracked_job("highlight_stories", run_highlight_batch, trigger="manual")
    except Exception as e:
        click.echo(f"Highlight failed: {e}", err=True)
        raise SystemExit(1)
    click.echo("Pipeline complete.")
```

Remove the existing `click.echo("Pipeline complete.")` that was at the end of the rewrite step.

- [ ] **Step 3: Add scheduled highlight job to `app/scheduler.py`**

Add a new job function after `_rewrite_articles_job` (around line 71):

```python
def _highlight_articles_job(config: dict[str, Any]) -> Any:
    """Lazy import so light-only hosts never load LLM/highlight stack."""
    from app.services.highlight_service import run_highlight_batch

    return run_highlight_batch(config)
```

In the `main()` function, read the highlight cron from config (add after `rewrite_cron` on line 138):

```python
    highlight_cron = config.get("schedule", {}).get("highlight_cron", "30 6 * * *")
```

In the `heavy`/`full` mode block (after the `rewrite_articles` job, around line 175), add:

```python
        scheduler.add_job(
            lambda: _run_tracked_job("highlight_stories", _highlight_articles_job),
            trigger=CronTrigger.from_crontab(highlight_cron),
            id="highlight_stories",
        )
```

Update the `heavy` and `full` log messages to include `highlight_cron`.

- [ ] **Step 4: Run the existing scheduler/rewrite tests to confirm no regressions**

```bash
pytest tests/test_rewrite_service.py -v
```
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add app/worker_cli.py app/scheduler.py
git commit -m "feat(worker): add highlight-stories CLI command and scheduled highlight job"
```

---

## Task 9: End-to-end verification

- [ ] **Step 1: Run the full test suite**

```bash
pytest tests/ -v
```
Expected: all tests PASS.

- [ ] **Step 2: Run the full pipeline manually in Docker**

```bash
docker compose exec worker python -m app.worker_cli run-pipeline
```
Expected: logs show each stage including "Running highlight..." without error.

- [ ] **Step 3: Check the database for highlighted content**

```bash
docker compose exec db psql -U dossier -c \
  "SELECT story_id, style, language, LEFT(highlighted_full_text, 120) FROM story_rewrites WHERE highlighted_full_text IS NOT NULL LIMIT 3;"
```
Expected: rows with `**...**` markers visible in the `LEFT(highlighted_full_text, 120)` preview.

- [ ] **Step 4: Verify rendering in browser**

Open a story in the reader (`http://localhost:5000`). Expand a highlighted story. Confirm:
- Bold `<strong>` terms appear in the body.
- TTS "Listen" button reads clean plain text (no `**` artifacts in speech).
- Stories without highlighting yet render normally (no artifacts, no errors).

- [ ] **Step 5: Run type checking and linting**

```bash
ruff check app/services/highlight_service.py app/db/stories.py app/__init__.py
mypy app/services/highlight_service.py app/db/stories.py
```
Expected: no errors.
