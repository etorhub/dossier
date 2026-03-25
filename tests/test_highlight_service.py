"""Tests for highlight_service."""

from unittest.mock import MagicMock, patch


def _llm_config() -> dict:
    """Config that selects the LLM highlight path."""
    return {"processing": {"rewrite_max_tokens": 2048, "highlight_method": "llm"}}


def _ner_config() -> dict:
    """Config that selects the NER highlight path (default)."""
    return {"processing": {}}


# ---------------------------------------------------------------------------
# LLM path tests
# ---------------------------------------------------------------------------

def test_highlight_story_llm_stores_result_on_success() -> None:
    """highlight_story (llm) calls LLM, stores result, returns True."""
    mock_provider = MagicMock()
    mock_provider.complete.return_value = "The **president** spoke at the **White House**."

    with patch("app.services.highlight_service.db_stories") as mock_db, \
         patch("app.llm.prompts.load_prompt", return_value="Text:\n{full_text}"):
        from app.services.highlight_service import highlight_story
        result = highlight_story(
            story_id="story-1",
            full_text="The president spoke at the White House.",
            style="neutral",
            language="en",
            config=_llm_config(),
            provider=mock_provider,
        )

    assert result is True
    mock_db.update_story_rewrite_highlight.assert_called_once_with(
        "story-1", "neutral", "en", "The **president** spoke at the **White House**."
    )


def test_highlight_story_llm_returns_false_on_llm_failure() -> None:
    """highlight_story (llm) returns False when LLM raises, does not propagate."""
    mock_provider = MagicMock()
    mock_provider.complete.side_effect = RuntimeError("LLM down")

    with patch("app.services.highlight_service.db_stories"), \
         patch("app.llm.prompts.load_prompt", return_value="Text:\n{full_text}"):
        from app.services.highlight_service import highlight_story
        result = highlight_story(
            story_id="story-1",
            full_text="Some text.",
            style="neutral",
            language="en",
            config=_llm_config(),
            provider=mock_provider,
        )

    assert result is False


def test_highlight_story_llm_returns_false_on_empty_response() -> None:
    """highlight_story (llm) returns False when LLM returns empty string."""
    mock_provider = MagicMock()
    mock_provider.complete.return_value = "   "

    with patch("app.services.highlight_service.db_stories"), \
         patch("app.llm.prompts.load_prompt", return_value="Text:\n{full_text}"):
        from app.services.highlight_service import highlight_story
        result = highlight_story(
            story_id="story-1",
            full_text="Some text.",
            style="neutral",
            language="en",
            config=_llm_config(),
            provider=mock_provider,
        )

    assert result is False


# ---------------------------------------------------------------------------
# NER path tests
# ---------------------------------------------------------------------------

def test_highlight_story_ner_bolds_title_case_phrases() -> None:
    """highlight_story (ner) wraps multi-word Title Case phrases in **bold**."""
    with patch("app.services.highlight_service.db_stories") as mock_db:
        from app.services.highlight_service import highlight_story
        result = highlight_story(
            story_id="story-2",
            full_text="Joe Biden met with Angela Merkel at the White House.",
            style="neutral",
            language="en",
            config=_ner_config(),
        )

    assert result is True
    call_args = mock_db.update_story_rewrite_highlight.call_args
    highlighted = call_args[0][3]  # 4th positional arg
    assert "**" in highlighted  # some bolding occurred


def test_highlight_story_ner_returns_true_on_plain_text() -> None:
    """highlight_story (ner) returns True even when nothing is highlighted."""
    with patch("app.services.highlight_service.db_stories") as mock_db:
        from app.services.highlight_service import highlight_story
        result = highlight_story(
            story_id="story-3",
            full_text="no entities here at all.",
            style="neutral",
            language="en",
            config=_ner_config(),
        )

    assert result is True
    mock_db.update_story_rewrite_highlight.assert_called_once()


def test_highlight_ner_regex_bolds_only_first_occurrence() -> None:
    """_highlight_ner_regex bolds each Title Case phrase only on its first occurrence."""
    from app.services.highlight_service import _highlight_ner_regex

    text = "Joe Biden met Angela Merkel. Later, Joe Biden left."
    result = _highlight_ner_regex(text)

    assert result.count("**Joe Biden**") == 1
    assert result.count("**Angela Merkel**") == 1
    # Second occurrence of Joe Biden must not be wrapped
    assert "Later, Joe Biden left." in result


def test_highlight_ner_spacy_bolds_only_first_occurrence() -> None:
    """highlight_story (ner) bolds each entity only once, falling back to regex when spaCy absent."""
    with patch("app.services.highlight_service._load_spacy", return_value=None), \
         patch("app.services.highlight_service.db_stories") as mock_db:
        from app.services.highlight_service import highlight_story
        highlight_story(
            story_id="story-ded",
            full_text="Joe Biden met Angela Merkel. Later, Joe Biden left.",
            style="neutral",
            language="en",
            config=_ner_config(),
        )

    highlighted = mock_db.update_story_rewrite_highlight.call_args[0][3]
    assert highlighted.count("**Joe Biden**") == 1
    assert highlighted.count("**Angela Merkel**") == 1
    assert "Later, Joe Biden left." in highlighted


# ---------------------------------------------------------------------------
# run_highlight_batch tests
# ---------------------------------------------------------------------------

def test_run_highlight_batch_llm_returns_report() -> None:
    """run_highlight_batch (llm) processes rows and returns HighlightReport."""
    rows = [
        {"story_id": "s1", "style": "neutral", "language": "en", "full_text": "Text one."},
        {"story_id": "s2", "style": "neutral", "language": "en", "full_text": "Text two."},
    ]
    mock_provider = MagicMock()
    mock_provider.complete.return_value = "Text **one**."

    with patch("app.services.highlight_service.db_stories") as mock_db, \
         patch("app.llm.provider.get_provider", return_value=mock_provider), \
         patch("app.llm.prompts.load_prompt", return_value="Text:\n{full_text}"):
        mock_db.get_stories_needing_highlight.return_value = rows
        from app.services.highlight_service import run_highlight_batch
        report = run_highlight_batch(_llm_config())

    assert report.attempted == 2
    assert report.succeeded == 2
    assert report.failed == 0


def test_run_highlight_batch_empty_returns_zero_report() -> None:
    """run_highlight_batch with no rows returns HighlightReport(0, 0, 0)."""
    with patch("app.services.highlight_service.db_stories") as mock_db:
        mock_db.get_stories_needing_highlight.return_value = []
        from app.services.highlight_service import run_highlight_batch
        report = run_highlight_batch({"processing": {}})

    assert report.attempted == 0
    assert report.succeeded == 0
    assert report.failed == 0


def test_run_highlight_batch_ner_processes_rows() -> None:
    """run_highlight_batch (ner, default) processes rows without LLM calls."""
    rows = [
        {"story_id": "s1", "style": "neutral", "language": "en", "full_text": "Barack Obama spoke."},
    ]
    with patch("app.services.highlight_service.db_stories") as mock_db:
        mock_db.get_stories_needing_highlight.return_value = rows
        from app.services.highlight_service import run_highlight_batch
        report = run_highlight_batch(_ner_config())

    assert report.attempted == 1
    assert report.succeeded == 1
    assert report.failed == 0
