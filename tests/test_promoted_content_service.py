"""Tests for sponsored / native-ad detection in the reader feed."""

from app.services.promoted_content_service import (
    article_looks_promoted,
    exclude_promoted_articles,
)


def _cfg() -> dict:
    return {
        "feed": {
            "promoted_content": {
                "enabled": True,
                "body_prefix_chars": 400,
                "patterns": [
                    "contenido patrocinado",
                    "con la colaboracion de",
                ],
            },
        },
    }


def test_article_looks_promoted_title_spanish() -> None:
    art = {"title": "Foo | Contenido patrocinado", "raw_text": "", "full_text": ""}
    assert article_looks_promoted(art, _cfg()) is True


def test_article_looks_promoted_title_accent_insensitive() -> None:
    art = {
        "title": "Noticia con la colaboración de ACME",
        "raw_text": "",
        "full_text": "",
    }
    assert article_looks_promoted(art, _cfg()) is True


def test_article_looks_promoted_in_body_prefix() -> None:
    art = {
        "title": "Headline",
        "raw_text": "<p>Contenido patrocinado</p><p>Rest of piece.</p>",
        "full_text": "",
    }
    assert article_looks_promoted(art, _cfg()) is True


def test_article_looks_promoted_false_when_clean() -> None:
    art = {
        "title": "Normal headline",
        "raw_text": "Regular lede without markers.",
        "full_text": "",
    }
    assert article_looks_promoted(art, _cfg()) is False


def test_article_looks_promoted_disabled() -> None:
    cfg = {
        "feed": {
            "promoted_content": {
                "enabled": False,
                "patterns": ["contenido patrocinado"],
            },
        },
    }
    art = {"title": "Contenido patrocinado", "raw_text": "", "full_text": ""}
    assert article_looks_promoted(art, cfg) is False


def test_exclude_promoted_keeps_clean_articles() -> None:
    clean = {"title": "News", "raw_text": "Text", "full_text": ""}
    dirty = {"title": "Contenido patrocinado", "raw_text": "", "full_text": ""}
    out = exclude_promoted_articles([clean, dirty], _cfg())
    assert out == [clean]
