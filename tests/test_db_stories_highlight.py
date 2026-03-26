"""Tests for story highlight DB functions."""

from unittest.mock import MagicMock, patch


def test_update_story_rewrite_highlight_executes_update() -> None:
    """update_story_rewrite_highlight issues an UPDATE SQL statement."""
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_conn.cursor.return_value.__enter__ = lambda s: mock_cur
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

    with (
        patch("app.db.stories.get_connection", return_value=mock_conn),
        patch("app.db.stories.return_connection"),
    ):
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
        {
            "story_id": "abc",
            "style": "neutral",
            "language": "en",
            "full_text": "Some text.",
        }
    ]
    mock_conn.cursor.return_value.__enter__ = lambda s: mock_cur
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

    with (
        patch("app.db.stories.get_connection", return_value=mock_conn),
        patch("app.db.stories.return_connection"),
    ):
        from app.db.stories import get_stories_needing_highlight

        rows = get_stories_needing_highlight()

    assert isinstance(rows, list)
    assert rows[0]["story_id"] == "abc"


def test_get_story_rewrites_includes_highlighted_full_text() -> None:
    """get_story_rewrites SELECT includes highlighted_full_text column."""
    mock_conn = MagicMock()
    mock_cur = MagicMock()
    mock_cur.fetchall.return_value = []
    mock_conn.cursor.return_value.__enter__ = lambda s: mock_cur
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)

    with (
        patch("app.db.stories.get_connection", return_value=mock_conn),
        patch("app.db.stories.return_connection"),
    ):
        from app.db.stories import get_story_rewrites

        get_story_rewrites(["story-1"], "neutral", "en")

    sql = mock_cur.execute.call_args[0][0]
    assert "highlighted_full_text" in sql


def test_get_articles_for_stories_empty_list_returns_empty_dict() -> None:
    """get_articles_for_stories([]) returns {} without touching the DB."""
    with patch("app.db.stories.get_connection") as mock_get_conn:
        from app.db.stories import get_articles_for_stories

        result = get_articles_for_stories([])
    assert result == {}
    mock_get_conn.assert_not_called()


def test_get_all_rewrites_for_stories_empty_list_returns_empty_dict() -> None:
    """get_all_rewrites_for_stories([]) returns {} without touching the DB."""
    with patch("app.db.stories.get_connection") as mock_get_conn:
        from app.db.stories import get_all_rewrites_for_stories

        result = get_all_rewrites_for_stories([])
    assert result == {}
    mock_get_conn.assert_not_called()
