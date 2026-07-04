"""Tests for static frontend assets."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_dossier_css_exists() -> None:
    css_path = ROOT / "app" / "static" / "dossier.css"
    assert css_path.is_file()
    content = css_path.read_text(encoding="utf-8")
    assert "--touch-min:    48px" in content
    assert "--error:" in content


def test_base_html_links_dossier_css() -> None:
    base_html = (ROOT / "templates" / "base.html").read_text(encoding="utf-8")
    assert "dossier.css" in base_html
    assert "<style>" not in base_html
