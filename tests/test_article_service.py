"""Tests for article_service feed logic."""

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

from app.services.article_service import get_feed, select_story_image


def test_get_feed_multi_source_ranks_above_singleton() -> None:
    """Multi-source clusters appear before singletons regardless of recency."""
    now = datetime.now(UTC)
    one_hour_ago = now - timedelta(hours=1)

    # Singleton (1 source) - very fresh
    cluster_singleton = {
        "cluster_id": "c-singleton",
        "articles": [
            {
                "id": "a1",
                "source_id": "s1",
                "published_at": now,
                "url": "https://s1.com/1",
                "title": "Singleton",
            },
        ],
    }
    # Multi-source (2 sources) - slightly older
    cluster_multi = {
        "cluster_id": "c-multi",
        "articles": [
            {
                "id": "a2",
                "source_id": "s1",
                "published_at": one_hour_ago,
                "url": "https://s1.com/2",
                "title": "Multi",
            },
            {
                "id": "a3",
                "source_id": "s2",
                "published_at": one_hour_ago,
                "url": "https://s2.com/1",
                "title": "Multi",
            },
        ],
    }

    sources = {
        "s1": {"id": "s1", "name": "Source 1", "topics": ["politics"]},
        "s2": {"id": "s2", "name": "Source 2", "topics": ["politics"]},
    }

    with (
        patch("app.services.article_service.profile_service") as mock_ps,
        patch("app.services.article_service.load_sources") as mock_load_sources,
        patch("app.services.article_service.load_config") as mock_load_config,
        patch("app.services.article_service.db_stories") as mock_db,
    ):
        mock_ps.get_profile_with_selections.return_value = {
            "topic_ids": ["politics"],
        }
        mock_ps.get_reading_variant.return_value = ("neutral", "ca")
        mock_load_sources.return_value = list(sources.values())
        mock_load_config.return_value = {
            "processing": {"cluster_window_hours": 24, "articles_per_day": 10},
            "relevance": {"min_sources": 2},
            "rewriting": {"default_style": "neutral", "default_language": "ca"},
        }
        mock_db.get_stories_with_articles_in_window.return_value = [
            {"story_id": "c-singleton"},
            {"story_id": "c-multi"},
        ]
        mock_db.get_articles_in_story.side_effect = [
            cluster_singleton["articles"],
            cluster_multi["articles"],
        ]
        mock_db.get_story_rewrites.return_value = {
            "c-singleton": {"title": "Singleton", "summary": "", "full_text": "Text"},
            "c-multi": {"title": "Multi", "summary": "", "full_text": "Text"},
        }

        feed, _ = get_feed(user_id=1)

        # With min_sources=2, only multi-source stories appear; singleton is excluded
        ids = [item["id"] for item in feed]
        assert "c-multi" in ids
        assert "c-singleton" not in ids
        assert ids[0] == "c-multi"


def test_get_feed_equal_scores_tie_break_by_story_id() -> None:
    """When relevance scores tie, ordering is stable by story_id (ascending)."""
    now = datetime.now(UTC)
    sources = {
        "s1": {"id": "s1", "name": "Source 1", "topics": ["politics"]},
    }
    art = {
        "id": "a1",
        "source_id": "s1",
        "published_at": now,
        "url": "u1",
        "title": "T",
    }

    with (
        patch("app.services.article_service.profile_service") as mock_ps,
        patch("app.services.article_service.load_sources") as mock_load_sources,
        patch("app.services.article_service.load_config") as mock_load_config,
        patch("app.services.article_service.db_stories") as mock_db,
        patch("app.services.article_service.score_story", return_value=0.5),
    ):
        mock_ps.get_profile_with_selections.return_value = {
            "topic_ids": ["politics"],
        }
        mock_ps.get_reading_variant.return_value = ("neutral", "ca")
        mock_load_sources.return_value = list(sources.values())
        mock_load_config.return_value = {
            "processing": {"cluster_window_hours": 24, "articles_per_day": 10},
            "relevance": {"min_sources": 1},
            "rewriting": {"default_style": "neutral", "default_language": "ca"},
        }
        # DB order deliberately reverse lexicographic vs desired feed order
        mock_db.get_stories_with_articles_in_window.return_value = [
            {"story_id": "c-zebra"},
            {"story_id": "c-apple"},
        ]
        mock_db.get_articles_in_story.side_effect = [
            [art],
            [art],
        ]
        mock_db.get_story_rewrites.return_value = {
            "c-zebra": {"title": "Z", "summary": "", "full_text": "T"},
            "c-apple": {"title": "A", "summary": "", "full_text": "T"},
        }

        feed, _ = get_feed(user_id=1)

        assert [item["id"] for item in feed] == ["c-apple", "c-zebra"]


def test_get_feed_backfill_when_few_multi_source() -> None:
    """Fallback singletons fill feed when fewer multi-source stories than limit (min_sources=1)."""
    now = datetime.now(UTC)
    sources = {
        "s1": {"id": "s1", "name": "Source 1", "topics": ["politics"]},
        "s2": {"id": "s2", "name": "Source 2", "topics": ["politics"]},
    }

    # One multi-source story, two singletons; limit 3; min_sources=1 so singletons appear
    cluster_multi = {
        "cluster_id": "c-multi",
        "articles": [
            {
                "id": "a1",
                "source_id": "s1",
                "published_at": now,
                "url": "u1",
                "title": "M",
            },
            {
                "id": "a2",
                "source_id": "s2",
                "published_at": now,
                "url": "u2",
                "title": "M",
            },
        ],
    }
    art_s1 = {
        "id": "a3",
        "source_id": "s1",
        "published_at": now,
        "url": "u3",
        "title": "S1",
    }
    art_s2 = {
        "id": "a4",
        "source_id": "s2",
        "published_at": now,
        "url": "u4",
        "title": "S2",
    }
    cluster_s1 = {"cluster_id": "c-s1", "articles": [art_s1]}
    cluster_s2 = {"cluster_id": "c-s2", "articles": [art_s2]}

    with (
        patch("app.services.article_service.profile_service") as mock_ps,
        patch("app.services.article_service.load_sources") as mock_load_sources,
        patch("app.services.article_service.load_config") as mock_load_config,
        patch("app.services.article_service.db_stories") as mock_db,
    ):
        mock_ps.get_profile_with_selections.return_value = {
            "topic_ids": ["politics"],
        }
        mock_ps.get_reading_variant.return_value = ("neutral", "ca")
        mock_load_sources.return_value = list(sources.values())
        mock_load_config.return_value = {
            "processing": {"cluster_window_hours": 24, "articles_per_day": 3},
            "relevance": {"min_sources": 1},
            "rewriting": {"default_style": "neutral", "default_language": "ca"},
        }
        mock_db.get_stories_with_articles_in_window.return_value = [
            {"story_id": "c-multi"},
            {"story_id": "c-s1"},
            {"story_id": "c-s2"},
        ]
        mock_db.get_articles_in_story.side_effect = [
            cluster_multi["articles"],
            cluster_s1["articles"],
            cluster_s2["articles"],
        ]
        mock_db.get_story_rewrites.return_value = {
            "c-multi": {"title": "Multi", "summary": "", "full_text": "T"},
            "c-s1": {"title": "S1", "summary": "", "full_text": "T"},
            "c-s2": {"title": "S2", "summary": "", "full_text": "T"},
        }

        feed, _ = get_feed(user_id=1)

        assert len(feed) == 3
        assert feed[0]["id"] == "c-multi"
        # Equal scores: stable tie-break by story_id ascending
        assert feed[1]["id"] == "c-s1"
        assert feed[2]["id"] == "c-s2"


def test_get_feed_min_sources_one_disables_filter() -> None:
    """min_sources: 1 treats all clusters as primary (backward compatible)."""
    now = datetime.now(UTC)
    art = {
        "id": "a1",
        "source_id": "s1",
        "published_at": now,
        "url": "u1",
        "title": "T",
    }
    cluster_singleton = {"cluster_id": "c1", "articles": [art]}

    sources = {"s1": {"id": "s1", "name": "Source 1", "topics": ["politics"]}}

    with (
        patch("app.services.article_service.profile_service") as mock_ps,
        patch("app.services.article_service.load_sources") as mock_load_sources,
        patch("app.services.article_service.load_config") as mock_load_config,
        patch("app.services.article_service.db_stories") as mock_db,
    ):
        mock_ps.get_profile_with_selections.return_value = {
            "topic_ids": ["politics"],
        }
        mock_ps.get_reading_variant.return_value = ("neutral", "ca")
        mock_load_sources.return_value = list(sources.values())
        mock_load_config.return_value = {
            "processing": {"cluster_window_hours": 24, "articles_per_day": 10},
            "relevance": {"min_sources": 1},
            "rewriting": {"default_style": "neutral", "default_language": "ca"},
        }
        mock_db.get_stories_with_articles_in_window.return_value = [
            {"story_id": "c1"},
        ]
        mock_db.get_articles_in_story.return_value = cluster_singleton["articles"]
        mock_db.get_story_rewrites.return_value = {
            "c1": {"title": "Title", "summary": "", "full_text": "Text"},
        }

        feed, _ = get_feed(user_id=1)

        assert len(feed) == 1
        assert feed[0]["id"] == "c1"


def test_get_feed_excludes_story_when_promoted_strips_below_min_sources() -> None:
    """After removing sponsored items, stories with too few distinct sources are omitted."""
    now = datetime.now(UTC)
    sources = {
        "s1": {"id": "s1", "name": "Source 1", "topics": ["politics"]},
        "s2": {"id": "s2", "name": "Source 2", "topics": ["politics"]},
    }
    articles = [
        {
            "id": "a1",
            "source_id": "s1",
            "published_at": now,
            "url": "https://s1.com/1",
            "title": "Real headline",
            "raw_text": "Body",
            "full_text": "",
        },
        {
            "id": "a2",
            "source_id": "s2",
            "published_at": now,
            "url": "https://s2.com/1",
            "title": "Contenido patrocinado",
            "raw_text": "",
            "full_text": "",
        },
    ]

    with (
        patch("app.services.article_service.profile_service") as mock_ps,
        patch("app.services.article_service.load_sources") as mock_load_sources,
        patch("app.services.article_service.load_config") as mock_load_config,
        patch("app.services.article_service.db_stories") as mock_db,
    ):
        mock_ps.get_profile_with_selections.return_value = {
            "topic_ids": ["politics"],
        }
        mock_ps.get_reading_variant.return_value = ("neutral", "ca")
        mock_load_sources.return_value = list(sources.values())
        mock_load_config.return_value = {
            "processing": {"cluster_window_hours": 24, "articles_per_day": 10},
            "relevance": {"min_sources": 2},
            "rewriting": {"default_style": "neutral", "default_language": "ca"},
            "feed": {
                "promoted_content": {
                    "enabled": True,
                    "body_prefix_chars": 400,
                    "patterns": ["contenido patrocinado"],
                },
            },
        }
        mock_db.get_stories_with_articles_in_window.return_value = [
            {"story_id": "c-mixed"},
        ]
        mock_db.get_articles_in_story.return_value = articles
        mock_db.get_story_rewrites.return_value = {
            "c-mixed": {"title": "T", "summary": "", "full_text": "Text"},
        }

        feed, _ = get_feed(user_id=1)

        assert feed == []


def test_get_feed_excludes_read_stories() -> None:
    """Stories marked as read are excluded from the feed (when read tracking is implemented)."""
    now = datetime.now(UTC)
    art = {
        "id": "a1",
        "source_id": "s1",
        "published_at": now,
        "url": "u1",
        "title": "T",
    }
    story = {"story_id": "c1", "articles": [art]}

    sources = {"s1": {"id": "s1", "name": "Source 1", "topics": ["politics"]}}

    with (
        patch("app.services.article_service.profile_service") as mock_ps,
        patch("app.services.article_service.load_sources") as mock_load_sources,
        patch("app.services.article_service.load_config") as mock_load_config,
        patch("app.services.article_service.db_stories") as mock_db,
    ):
        mock_ps.get_profile_with_selections.return_value = {
            "topic_ids": ["politics"],
        }
        mock_ps.get_reading_variant.return_value = ("neutral", "ca")
        mock_load_sources.return_value = list(sources.values())
        mock_load_config.return_value = {
            "processing": {"cluster_window_hours": 24, "articles_per_day": 10},
            "relevance": {"min_sources": 1},
            "rewriting": {"default_style": "neutral", "default_language": "ca"},
        }
        mock_db.get_stories_with_articles_in_window.return_value = [
            {"story_id": "c1"},
        ]
        mock_db.get_articles_in_story.return_value = story["articles"]
        mock_db.get_story_rewrites.return_value = {
            "c1": {"title": "Title", "summary": "", "full_text": "Text"},
        }

        feed, _ = get_feed(user_id=1)

        # Read tracking not yet implemented; feed includes the story
        assert len(feed) == 1


def test_select_story_image_prefers_media_content_over_og_image() -> None:
    """media_content image is preferred over og_image."""
    now = datetime.now(UTC)
    articles = [
        {
            "id": "a1",
            "source_id": "s1",
            "image_url": "https://s1.com/og.jpg",
            "image_source": "og_image",
            "published_at": now,
        },
        {
            "id": "a2",
            "source_id": "s2",
            "image_url": "https://s2.com/media.jpg",
            "image_source": "media_content",
            "published_at": now,
        },
    ]
    sources = {"s1": {}, "s2": {}}
    url, _ = select_story_image(articles, sources)
    assert url == "https://s2.com/media.jpg"


def test_select_story_image_prefers_article_body_over_media_content() -> None:
    """article_body (Trafilatura main) beats feed media_content."""
    now = datetime.now(UTC)
    articles = [
        {
            "id": "a1",
            "source_id": "s1",
            "image_url": "https://s1.com/feed.jpg",
            "image_source": "media_content",
            "published_at": now,
        },
        {
            "id": "a2",
            "source_id": "s2",
            "image_url": "https://s2.com/body.jpg",
            "image_source": "article_body",
            "published_at": now,
        },
    ]
    sources = {"s1": {}, "s2": {}}
    url, _ = select_story_image(articles, sources)
    assert url == "https://s2.com/body.jpg"


def test_select_story_image_uses_earliest_published_as_tiebreaker() -> None:
    """When image_source scores are equal, earliest published_at wins."""
    earlier = datetime(2024, 1, 1, 10, 0, 0, tzinfo=UTC)
    later = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
    articles = [
        {
            "id": "a1",
            "source_id": "s1",
            "image_url": "https://s1.com/later.jpg",
            "image_source": "og_image",
            "published_at": later,
        },
        {
            "id": "a2",
            "source_id": "s2",
            "image_url": "https://s2.com/earlier.jpg",
            "image_source": "og_image",
            "published_at": earlier,
        },
    ]
    sources = {"s1": {}, "s2": {}}
    url, _ = select_story_image(articles, sources)
    assert url == "https://s2.com/earlier.jpg"


def test_select_story_image_returns_none_when_no_images() -> None:
    """Returns None when no articles have images."""
    articles = [
        {"id": "a1", "source_id": "s1", "image_url": None, "published_at": None},
    ]
    url, _ = select_story_image(articles, {})
    assert url is None


def test_select_story_image_returns_none_for_empty_articles() -> None:
    """Returns None for empty article list."""
    url, _ = select_story_image([], {})
    assert url is None


def test_select_story_image_uses_fallback_for_unknown_source() -> None:
    """Images with unknown image_source use fallback score and are displayed."""
    articles = [
        {
            "id": "a1",
            "source_id": "s1",
            "image_url": "https://example.com/newly-incorporated.jpg",
            "image_source": "unknown_source",
            "published_at": None,
        },
    ]
    url, _ = select_story_image(articles, {})
    assert url == "https://example.com/newly-incorporated.jpg"


def test_select_story_image_prefers_known_source_over_unknown() -> None:
    """Known image_source (og_image) wins over unknown image_source."""
    articles = [
        {
            "id": "a1",
            "source_id": "s1",
            "image_url": "https://example.com/unknown.jpg",
            "image_source": "other",
            "published_at": None,
        },
        {
            "id": "a2",
            "source_id": "s2",
            "image_url": "https://example.com/og.jpg",
            "image_source": "og_image",
            "published_at": None,
        },
    ]
    url, _ = select_story_image(articles, {})
    assert url == "https://example.com/og.jpg"
