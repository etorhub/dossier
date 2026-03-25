"""Tests for rewrite service."""

from unittest.mock import MagicMock, patch

import pytest

from app.services.rewrite_service import (
    RewriteReport,
    _build_articles_text_for_rewrite,
    _get_language_writing_note,
    _llm_task_temperature,
    _parse_cluster_llm_response,
    _strip_markdown_bold,
    _writing_note_section_for_translate,
    rewrite_story,
    run_rewrite_all_stories,
    run_rewrite_batch,
)


def test_build_articles_text_for_rewrite_caps_source_count() -> None:
    """Large clusters only send the first N sources to the rewrite model."""
    arts = [
        {"title": f"T{i}", "full_text": "body", "raw_text": ""} for i in range(25)
    ]
    text, meta = _build_articles_text_for_rewrite(
        arts,
        {"rewrite_max_sources_per_story": 6, "rewrite_max_chars_per_article": 0, "rewrite_max_articles_text_chars": 0},
    )
    assert meta["sources_total"] == 25
    assert meta["sources_used"] == 6
    assert meta["capped_source_count"] is True
    assert text.count("[Source ") == 6


def test_build_articles_text_for_rewrite_hard_cap_total_chars() -> None:
    """articles_text is cut when merged body exceeds rewrite_max_articles_text_chars."""
    arts = [{"title": "A", "full_text": "x" * 5000, "raw_text": ""} for _ in range(20)]
    text, meta = _build_articles_text_for_rewrite(
        arts,
        {
            "rewrite_max_sources_per_story": 0,
            "rewrite_max_chars_per_article": 0,
            "rewrite_max_articles_text_chars": 3000,
        },
    )
    assert meta["hard_truncated"] is True
    assert len(text) <= 3200


def test_parse_cluster_llm_response_happy() -> None:
    """_parse_cluster_llm_response extracts title, summary and full text."""
    text = """TITLE:
Power outage affects 500 homes.

SUMMARY:
First sentence. Second sentence. Third sentence.

FULL:
This is the full simplified article. Short sentences. Simple words."""
    title, summary, full = _parse_cluster_llm_response(text)
    assert "Power outage" in title
    assert "First sentence" in summary
    assert "This is the full simplified article" in full


def test_parse_cluster_llm_response_spanish_section_headers() -> None:
    """Localized Spanish headers are normalized and parsed."""
    text = """TÍTULO:
Corte de luz en el barrio.

RESUMEN:
Primera frase. Segunda frase. Tercera frase.

COMPLETO:
Texto del artículo completo aquí."""
    title, summary, full = _parse_cluster_llm_response(text)
    assert "Corte de luz" in title
    assert "Primera frase" in summary
    assert "Texto del artículo completo" in full


def test_parse_cluster_llm_response_catalan_text_complet_header() -> None:
    """Catalan TEXT COMPLET / RESUM / TÍTOL headers parse correctly."""
    text = """TÍTOL:
Títol català.

RESUM:
Una dos tres.

TEXT COMPLET:
Cos de l'article."""
    title, summary, full = _parse_cluster_llm_response(text)
    assert "Títol català" in title
    assert "Una dos tres" in summary
    assert "Cos de l'article" in full


def test_parse_cluster_llm_response_markdown_atx_headers() -> None:
    """Markdown ## headers are normalized and parsed."""
    text = """## TÍTULO:
Titular en español.

### RESUMEN:
Una frase. Dos frases. Tres frases.

## COMPLETO:
Cuerpo del artículo unificado."""
    title, summary, full = _parse_cluster_llm_response(text)
    assert "Titular" in title
    assert "Una frase" in summary
    assert "Cuerpo del artículo" in full


def test_parse_cluster_llm_response_fenced_markdown_block() -> None:
    """Leading ``` fence is stripped so TITLE:/SUMMARY:/FULL: parse."""
    text = """```text
TITLE:
Headline here.

SUMMARY:
One. Two. Three.

FULL:
Full body text.
```"""
    title, summary, full = _parse_cluster_llm_response(text)
    assert "Headline" in title
    assert "One." in summary
    assert "Full body" in full


def test_parse_cluster_llm_response_strips_preamble_before_title() -> None:
    """Chatter before the first TITLE: line is ignored."""
    text = """Here is the merged story.

TITLE:
Headline after preamble.

SUMMARY:
First sentence. Second sentence. Third sentence.

FULL:
Unified article body."""
    title, summary, full = _parse_cluster_llm_response(text)
    assert "Headline after preamble" in title
    assert "First sentence" in summary
    assert "Unified article body" in full


def test_parse_cluster_llm_response_empty_title_derived_from_summary() -> None:
    """Blank TITLE: body is filled from the first summary sentence (model quirk)."""
    text = """TITLE:

SUMMARY:
El FC Barcelona gana en Champions. El equipo mostró solidez defensiva.

FULL:
El FC Barcelona ha tenido un rendimiento sólido en la Liga de Campeones."""
    title, summary, full = _parse_cluster_llm_response(text)
    assert "Barcelona" in title or "Champions" in title
    assert "Champions" in summary
    assert "rendimiento" in full


def test_strip_markdown_bold() -> None:
    """_strip_markdown_bold removes ** from start and end of text."""
    assert _strip_markdown_bold("**Title here**") == "Title here"
    assert _strip_markdown_bold("** Power outage **") == "Power outage"
    assert _strip_markdown_bold("No asterisks") == "No asterisks"
    assert _strip_markdown_bold("**Only start") == "Only start"
    assert _strip_markdown_bold("Only end**") == "Only end"


def test_parse_cluster_llm_response_strips_markdown_bold() -> None:
    """_parse_cluster_llm_response strips ** from title, summary and full_text."""
    text = """TITLE:
**Power outage affects 500 homes.**

SUMMARY:
**First sentence. Second sentence. Third sentence.**

FULL:
**This is the full simplified article. Short sentences. Simple words.**"""
    title, summary, full = _parse_cluster_llm_response(text)
    assert title == "Power outage affects 500 homes."
    assert summary == "First sentence. Second sentence. Third sentence."
    assert full == "This is the full simplified article. Short sentences. Simple words."


def test_parse_cluster_llm_response_missing_title_raises() -> None:
    """_parse_cluster_llm_response raises ValueError when TITLE: missing."""
    text = "SUMMARY:\nS\nFULL:\nF"
    with pytest.raises(ValueError, match="missing TITLE"):
        _parse_cluster_llm_response(text)


def test_parse_cluster_llm_response_missing_full_raises() -> None:
    """_parse_cluster_llm_response raises ValueError when FULL: missing."""
    text = "TITLE:\nT\nSUMMARY:\nS"
    with pytest.raises(ValueError, match="TITLE:, SUMMARY:, or FULL:"):
        _parse_cluster_llm_response(text)


def test_parse_cluster_llm_response_empty_sections_raises() -> None:
    """_parse_cluster_llm_response raises ValueError when sections are empty."""
    text = "TITLE:\n\nSUMMARY:\n\nFULL:\n"
    with pytest.raises(ValueError, match="Empty"):
        _parse_cluster_llm_response(text)


def test_rewrite_cluster_empty_articles_stores_failed() -> None:
    """rewrite_cluster stores rewrite_failed=True when articles have no text."""
    with patch("app.services.rewrite_service.db_stories") as mock_db:
        articles = [{"id": "art1", "raw_text": "", "full_text": None}]
        config = {"rewriting": {"styles": [{"id": "neutral", "prompt": "rewrite_cluster_neutral"}]}}
        result = rewrite_story("story-1", articles, "neutral", "ca", config)
        assert result is False
        mock_db.insert_story_rewrite.assert_called_once_with(
            story_id="story-1",
            style="neutral",
            language="ca",
            title=None,
            summary=None,
            full_text=None,
            rewrite_failed=True,
            error_message="Articles have no full_text or raw_text",
        )


def test_rewrite_story_success_stores_rewrite() -> None:
    """rewrite_story stores title, summary and full_text on success."""
    with (
        patch("app.services.rewrite_service.db_stories") as mock_db,
        patch("app.services.rewrite_service.get_provider") as mock_get,
    ):
        mock_provider = MagicMock()
        mock_provider.complete.return_value = """TITLE:
Power outage in Barcelona.

SUMMARY:
One. Two. Three.

FULL:
Simplified article here."""
        mock_get.return_value = mock_provider

        articles = [
            {
                "id": "art1",
                "raw_text": "Original long article text.",
                "full_text": None,
            },
        ]
        config = {
            "processing": {"summary_sentences": 3},
            "rewriting": {"styles": [{"id": "neutral", "prompt": "rewrite_cluster_neutral"}]},
        }

        result = rewrite_story("story-1", articles, "neutral", "ca", config)
        assert result is True
        mock_db.insert_story_rewrite.assert_called_once_with(
            story_id="story-1",
            style="neutral",
            language="ca",
            title="Power outage in Barcelona.",
            summary="One. Two. Three.",
            full_text="Simplified article here.",
            rewrite_failed=False,
        )
        assert mock_provider.complete.call_count == 2  # draft + proofread
        draft_kwargs = mock_provider.complete.call_args_list[0][1]
        assert draft_kwargs["max_tokens"] == 4096  # default when not in config
        assert draft_kwargs["temperature"] == 0.2
        proof_kwargs = mock_provider.complete.call_args_list[1][1]
        assert proof_kwargs["temperature"] == 0.1


def test_rewrite_story_uses_config_max_tokens() -> None:
    """rewrite_story uses rewrite_max_tokens from config."""
    with (
        patch("app.services.rewrite_service.db_stories"),
        patch("app.services.rewrite_service.get_provider") as mock_get,
    ):
        mock_provider = MagicMock()
        mock_provider.complete.return_value = """TITLE:
Title.

SUMMARY:
Summary.

FULL:
Full text."""
        mock_get.return_value = mock_provider

        articles = [{"id": "art1", "raw_text": "Text", "full_text": None}]
        config = {
            "processing": {"rewrite_max_tokens": 1500},
            "rewriting": {"styles": [{"id": "neutral", "prompt": "rewrite_cluster_neutral"}]},
        }

        rewrite_story("story-1", articles, "neutral", "ca", config)

        assert mock_provider.complete.call_count == 2
        assert mock_provider.complete.call_args_list[0][1]["max_tokens"] == 1500
        assert mock_provider.complete.call_args_list[1][1]["max_tokens"] == 1500


def test_rewrite_story_skips_proofread_when_disabled() -> None:
    """rewrite_proofread_enabled False skips the second LLM call."""
    with (
        patch("app.services.rewrite_service.db_stories"),
        patch("app.services.rewrite_service.get_provider") as mock_get,
    ):
        mock_provider = MagicMock()
        mock_provider.complete.return_value = """TITLE:
T.

SUMMARY:
One. Two. Three.

FULL:
Full."""
        mock_get.return_value = mock_provider
        articles = [{"id": "art1", "raw_text": "x", "full_text": None}]
        config = {
            "processing": {"summary_sentences": 3, "rewrite_proofread_enabled": False},
            "rewriting": {"styles": [{"id": "neutral", "prompt": "rewrite_cluster_neutral"}]},
        }
        assert rewrite_story("story-x", articles, "neutral", "ca", config) is True
        mock_provider.complete.assert_called_once()


def test_rewrite_story_proofread_bad_response_keeps_draft() -> None:
    """When proofread output is unparseable, stored text is the draft."""
    valid = """TITLE:
H.

SUMMARY:
A. B. C.

FULL:
Body."""
    with (
        patch("app.services.rewrite_service.db_stories") as mock_db,
        patch("app.services.rewrite_service.get_provider") as mock_get,
    ):
        mock_provider = MagicMock()
        mock_provider.complete.side_effect = [valid, "no TITLE here"]
        mock_get.return_value = mock_provider
        articles = [{"id": "art1", "raw_text": "Text", "full_text": None}]
        config = {
            "processing": {"summary_sentences": 3},
            "rewriting": {"styles": [{"id": "neutral", "prompt": "rewrite_cluster_neutral"}]},
        }
        assert rewrite_story("s1", articles, "neutral", "ca", config) is True
        mock_db.insert_story_rewrite.assert_called_once_with(
            story_id="s1",
            style="neutral",
            language="ca",
            title="H.",
            summary="A. B. C.",
            full_text="Body.",
            rewrite_failed=False,
        )


def test_llm_task_temperature_defaults_and_override() -> None:
    """_llm_task_temperature uses llm config or built-in fallbacks."""
    assert _llm_task_temperature({}, "translate") == 0.15
    cfg = {"llm": {"translate_temperature": 0.05}}
    assert _llm_task_temperature(cfg, "translate") == 0.05


def test_writing_note_for_spanish_in_translate_section() -> None:
    """writing_note from rewriting.languages appears in translate section text."""
    config = {
        "rewriting": {
            "languages": [
                {
                    "id": "es",
                    "label": "Spanish",
                    "writing_note": "Use peninsular Spanish.",
                },
            ],
        },
    }
    assert _get_language_writing_note(config, "es") == "Use peninsular Spanish."
    sec = _writing_note_section_for_translate(config, "es")
    assert "Locale and register" in sec
    assert "Use peninsular Spanish." in sec
    assert _writing_note_section_for_translate(config, "en") == ""


def test_translate_article_prompt_has_required_placeholders() -> None:
    """translate_article template includes all keys used by rewrite_service.format."""
    from app.llm.prompts import load_prompt

    txt = load_prompt("translate_article")
    sample = txt.format(
        target_language="Spanish",
        style_description="Journalistic.",
        summary_sentences=3,
        writing_note_section="## Locale\nNote.\n",
        article_text="TITLE:\nT\n\nSUMMARY:\nS\n\nFULL:\nF",
    )
    assert "Spanish" in sample
    assert "Locale" in sample


def test_proofread_article_prompt_formats() -> None:
    """proofread_article template accepts title/summary/full blocks."""
    from app.llm.prompts import load_prompt

    p = load_prompt("proofread_article").format(
        language="Spanish",
        title="T",
        summary="S",
        full_text="F",
    )
    assert "Spanish" in p
    assert "TITLE:\nT" in p


def test_rewrite_story_provider_error_stores_failed() -> None:
    """rewrite_story stores rewrite_failed=True when provider raises."""
    from app.llm.provider import LLMProviderError

    with (
        patch("app.services.rewrite_service.db_stories") as mock_db,
        patch("app.services.rewrite_service.get_provider") as mock_get,
    ):
        mock_provider = MagicMock()
        mock_provider.complete.side_effect = LLMProviderError("API down")
        mock_get.return_value = mock_provider

        articles = [{"id": "art1", "raw_text": "Some text", "full_text": None}]
        config = {"rewriting": {"styles": [{"id": "neutral", "prompt": "rewrite_cluster_neutral"}]}}

        result = rewrite_story("story-1", articles, "neutral", "ca", config)
        assert result is False
        mock_db.insert_story_rewrite.assert_called_once_with(
            story_id="story-1",
            style="neutral",
            language="ca",
            title=None,
            summary=None,
            full_text=None,
            rewrite_failed=True,
            error_message="API down",
        )


def test_run_rewrite_batch_unlimited_passes_no_sql_limit() -> None:
    """rewrite_batch_size 0 passes limit=None so all pending stories are selected."""
    with patch("app.services.rewrite_service.db_stories") as mock_stories:
        mock_stories.get_stories_needing_any_rewrite.return_value = []
        config = {
            "schedule": {"rewrite_batch_size": 0},
            "processing": {"cluster_window_hours": 24},
            "rewriting": {
                "base_language": "en",
                "styles": [{"id": "neutral"}],
                "languages": [{"id": "ca"}, {"id": "en"}],
            },
        }
        run_rewrite_batch(config)
        mock_stories.get_stories_needing_any_rewrite.assert_called_once()
        call_kw = mock_stories.get_stories_needing_any_rewrite.call_args.kwargs
        assert call_kw["limit"] is None


def test_run_rewrite_batch_empty_variants() -> None:
    """run_rewrite_batch returns zero counts when no stories need rewrite."""
    with patch("app.services.rewrite_service.db_stories") as mock_stories:
        mock_stories.get_stories_needing_any_rewrite.return_value = []
        config = {
            "schedule": {"rewrite_batch_size": 10},
            "processing": {"cluster_window_hours": 24},
            "rewriting": {
                "base_language": "en",
                "styles": [{"id": "neutral"}],
                "languages": [{"id": "ca"}, {"id": "es"}, {"id": "en"}],
            },
        }
        report = run_rewrite_batch(config)
        assert report == RewriteReport(
            variants_processed=3,
            stories_attempted=0,
            stories_succeeded=0,
            stories_failed=0,
        )


def test_run_rewrite_batch_counts() -> None:
    """run_rewrite_batch returns correct counts for mixed success/failure."""
    with (
        patch("app.services.rewrite_service.db_stories") as mock_stories,
        patch("app.services.rewrite_service._execute_cascading_rewrites") as mock_execute,
        patch("app.services.rewrite_service.get_provider") as mock_get,
    ):
        mock_get.return_value = MagicMock()
        mock_stories.get_stories_needing_any_rewrite.return_value = [
            {"story_id": "c1", "needs_rewrite": True},
            {"story_id": "c2", "needs_rewrite": True},
        ]
        mock_stories.get_articles_for_stories.return_value = {
            "c1": [{"id": "a1", "raw_text": "t1", "full_text": None}],
            "c2": [{"id": "a2", "raw_text": "t2", "full_text": None}],
        }
        mock_execute.return_value = (5, 3)  # succeeded, failed

        config = {
            "schedule": {"rewrite_batch_size": 10},
            "processing": {"cluster_window_hours": 24},
            "rewriting": {
                "base_language": "en",
                "styles": [{"id": "neutral"}],
                "languages": [{"id": "ca"}, {"id": "es"}, {"id": "en"}],
            },
        }
        report = run_rewrite_batch(config)

        assert report.variants_processed == 3
        assert report.stories_attempted == 2
        assert report.stories_succeeded == 5
        assert report.stories_failed == 3


def test_run_rewrite_batch_calls_cascade() -> None:
    """run_rewrite_batch loads rewrite+translate when only neutral style is configured."""
    with (
        patch("app.services.rewrite_service.db_stories") as mock_stories,
        patch("app.services.rewrite_service.get_provider") as mock_get,
        patch("app.services.rewrite_service._execute_cascading_rewrites") as mock_execute,
    ):
        mock_get.return_value = MagicMock()
        mock_stories.get_stories_needing_any_rewrite.return_value = [
            {"story_id": "c1", "needs_rewrite": True},
        ]
        mock_stories.get_articles_for_stories.return_value = {
            "c1": [{"id": "a1", "raw_text": "t1", "full_text": None}],
        }
        mock_execute.return_value = (3, 0)  # all 3 variants succeeded

        config = {
            "schedule": {"rewrite_batch_size": 10},
            "processing": {"cluster_window_hours": 24},
            "rewriting": {
                "base_language": "en",
                "styles": [{"id": "neutral"}],
                "languages": [{"id": "ca"}, {"id": "es"}, {"id": "en"}],
            },
        }
        report = run_rewrite_batch(config)

        assert report.stories_attempted == 1
        assert report.stories_succeeded == 3
        mock_execute.assert_called_once()
        assert mock_get.call_count == 2
        tasks = [c[1]["task"] for c in mock_get.call_args_list if c[1].get("task")]
        assert "rewrite" in tasks
        assert "translate" in tasks
        assert "simplify" not in tasks


def test_run_rewrite_all_stories_uses_get_all_stories_and_full_regen() -> None:
    """run_rewrite_all_stories selects every story with articles and forces full cascade."""
    with (
        patch("app.services.rewrite_service.db_stories") as mock_stories,
        patch("app.services.rewrite_service.get_provider") as mock_get,
        patch("app.services.rewrite_service._execute_cascading_rewrites") as mock_execute,
    ):
        mock_get.return_value = MagicMock()
        mock_stories.get_all_stories_with_articles.return_value = [
            {"story_id": "s1"},
            {"story_id": "s2"},
        ]
        mock_stories.get_articles_for_stories.return_value = {
            "s1": [{"id": "a1", "raw_text": "t1", "full_text": None}],
            "s2": [{"id": "a2", "raw_text": "t2", "full_text": None}],
        }
        mock_execute.return_value = (4, 0)

        config = {
            "schedule": {"rewrite_batch_size": 10},
            "processing": {"cluster_window_hours": 24},
            "rewriting": {
                "base_language": "en",
                "styles": [{"id": "neutral"}],
                "languages": [{"id": "ca"}, {"id": "en"}],
            },
        }
        report = run_rewrite_all_stories(config)

        mock_stories.get_stories_needing_any_rewrite.assert_not_called()
        mock_stories.get_all_stories_with_articles.assert_called_once()
        assert mock_stories.get_all_stories_with_articles.call_args.kwargs["limit"] == 10

        mock_execute.assert_called_once()
        work = mock_execute.call_args.kwargs["work"]
        assert len(work) == 2
        assert all(w[2] is True for w in work)

        assert report.stories_attempted == 2
        assert report.stories_succeeded == 4


def test_run_rewrite_all_stories_unlimited_batch() -> None:
    """rewrite_batch_size 0 passes limit=None to get_all_stories_with_articles."""
    with (
        patch("app.services.rewrite_service.db_stories") as mock_stories,
        patch("app.services.rewrite_service.get_provider") as mock_get,
        patch("app.services.rewrite_service._execute_cascading_rewrites") as mock_execute,
    ):
        mock_get.return_value = MagicMock()
        mock_stories.get_all_stories_with_articles.return_value = []
        mock_execute.return_value = (0, 0)

        config = {
            "schedule": {"rewrite_batch_size": 0},
            "processing": {"cluster_window_hours": 24},
            "rewriting": {
                "base_language": "en",
                "styles": [{"id": "neutral"}],
                "languages": [{"id": "en"}],
            },
        }
        run_rewrite_all_stories(config)
        assert mock_stories.get_all_stories_with_articles.call_args.kwargs["limit"] is None


def test_gather_rewrite_work_returns_empty_when_no_stories() -> None:
    """_gather_rewrite_work returns [] immediately when no stories need rewrite."""
    from app.services.rewrite_service import _gather_rewrite_work

    with patch("app.services.rewrite_service.db_stories") as mock_stories:
        mock_stories.get_stories_needing_any_rewrite.return_value = []
        result = _gather_rewrite_work(variants=[("neutral", "en")], since=None, batch_size=10)
        assert result == []
        mock_stories.get_articles_for_stories.assert_not_called()


def test_gather_rewrite_work_uses_bulk_fetch() -> None:
    """_gather_rewrite_work calls get_articles_for_stories once for all stories."""
    from app.services.rewrite_service import _gather_rewrite_work

    with patch("app.services.rewrite_service.db_stories") as mock_stories:
        mock_stories.get_stories_needing_any_rewrite.return_value = [
            {"story_id": "s1", "needs_rewrite": False},
            {"story_id": "s2", "needs_rewrite": True},
        ]
        mock_stories.get_articles_for_stories.return_value = {
            "s1": [{"id": "a1", "raw_text": "text", "full_text": None}],
            "s2": [{"id": "a2", "raw_text": "text2", "full_text": None}],
        }
        result = _gather_rewrite_work(variants=[("neutral", "en")], since=None, batch_size=10)
        mock_stories.get_articles_for_stories.assert_called_once_with(["s1", "s2"])
        assert len(result) == 2
        assert result[0] == ("s1", [{"id": "a1", "raw_text": "text", "full_text": None}], False)
        assert result[1][2] is True
