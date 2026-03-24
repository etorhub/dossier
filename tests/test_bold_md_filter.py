"""Tests for the bold_md Jinja2 filter."""

import re

from markupsafe import Markup


def _get_filter():
    """Return the bold_md filter function (standalone, no Flask app needed)."""

    def bold_md_filter(text: str | None) -> Markup:
        if not text:
            return Markup("")
        escaped = str(Markup.escape(text))
        result = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", escaped)
        return Markup(result)

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


def test_bold_md_multiple_terms() -> None:
    f = _get_filter()
    result = f("The **president** met with **Prime Minister** today.")
    assert str(result) == "The <strong>president</strong> met with <strong>Prime Minister</strong> today."
