"""Tests for feed parser."""



from app.feed.parser import parse_feed

RSS_MINIMAL = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
<channel>
    <title>Test Feed</title>
    <item>
        <title>Article One</title>
        <link>https://example.com/1</link>
        <description>Short summary here.</description>
        <pubDate>Mon, 01 Jan 2024 12:00:00 GMT</pubDate>
    </item>
    <item>
        <title>Article Two</title>
        <link>https://example.com/2</link>
        <description><p>HTML <b>summary</b> here.</p></description>
        <pubDate>Tue, 02 Jan 2024 14:30:00 GMT</pubDate>
    </item>
</channel>
</rss>"""


RSS_WITH_CONTENT = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/">
<channel>
    <title>Full Text Feed</title>
    <item>
        <title>Full Article</title>
        <link>https://example.com/full</link>
        <description>Summary only</description>
        <content:encoded><![CDATA[<p>Full article body here.</p>]]></content:encoded>
        <pubDate>Wed, 03 Jan 2024 10:00:00 GMT</pubDate>
    </item>
</channel>
</rss>"""


RSS_MISSING_GUID = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
<channel>
    <title>No Guid</title>
    <item>
        <title>No Guid Item</title>
        <link>https://example.com/no-guid</link>
    </item>
</channel>
</rss>"""


def test_parse_feed_minimal_rss() -> None:
    """Parse minimal RSS returns normalized articles."""
    articles = parse_feed(RSS_MINIMAL)
    assert len(articles) == 2
    a1, a2 = articles[0], articles[1]
    assert a1["title"] == "Article One"
    assert a1["url"] == "https://example.com/1"
    assert a1["raw_text"] == "Short summary here."
    assert a1["full_text"] == ""
    assert a1["published_at"] is not None
    assert a1["published_at"].year == 2024

    assert a2["title"] == "Article Two"
    assert a2["url"] == "https://example.com/2"
    assert "HTML" in a2["raw_text"] and "summary" in a2["raw_text"]


def test_parse_feed_with_content_encoded() -> None:
    """Parse RSS with content:encoded extracts full text."""
    articles = parse_feed(RSS_WITH_CONTENT)
    assert len(articles) == 1
    a = articles[0]
    assert a["title"] == "Full Article"
    assert "Full article body" in a["full_text"]
    assert "Summary only" in a["raw_text"]


def test_parse_feed_missing_guid_uses_link() -> None:
    """When guid is missing, url is used as fallback."""
    articles = parse_feed(RSS_MISSING_GUID)
    assert len(articles) == 1
    assert articles[0]["url"] == "https://example.com/no-guid"
    assert articles[0]["guid"] == "https://example.com/no-guid"


def test_parse_feed_skips_entries_without_url() -> None:
    """Entries without link/url are skipped."""
    rss_no_link = b"""<?xml version="1.0"?>
    <rss version="2.0"><channel><title>X</title>
    <item><title>No link</title></item>
    </channel></rss>"""
    articles = parse_feed(rss_no_link)
    assert len(articles) == 0


def test_parse_feed_empty_content() -> None:
    """Empty or invalid content returns empty list."""
    assert parse_feed(b"") == []
    assert parse_feed(b"<html>not a feed</html>") == []


RSS_WITH_MEDIA_CONTENT = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:media="http://search.yahoo.com/mrss/">
<channel>
    <title>Media Feed</title>
    <item>
        <title>With Image</title>
        <link>https://example.com/with-image</link>
        <description>Summary</description>
        <media:content url="https://cdn.example.com/photo.jpg" medium="image" width="800" height="600"/>
        <pubDate>Mon, 01 Jan 2024 12:00:00 GMT</pubDate>
    </item>
</channel>
</rss>"""


RSS_WITH_ENCLOSURE = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
<channel>
    <title>Enclosure Feed</title>
    <item>
        <title>With Enclosure</title>
        <link>https://example.com/enclosure</link>
        <description>Summary</description>
        <enclosure url="https://cdn.example.com/thumb.png" type="image/png" length="5000"/>
        <pubDate>Mon, 01 Jan 2024 12:00:00 GMT</pubDate>
    </item>
</channel>
</rss>"""


RSS_WITH_IMG_IN_CONTENT = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/">
<channel>
    <title>Content Img Feed</title>
    <item>
        <title>With Img</title>
        <link>https://example.com/img</link>
        <description>Summary</description>
        <content:encoded><![CDATA[<p>Text</p><img src="https://example.com/lead.jpg" alt="Lead" />]]></content:encoded>
        <pubDate>Mon, 01 Jan 2024 12:00:00 GMT</pubDate>
    </item>
</channel>
</rss>"""


def test_parse_feed_extracts_media_content_image() -> None:
    """Parse RSS with media:content extracts image_url and image_source."""
    articles = parse_feed(RSS_WITH_MEDIA_CONTENT)
    assert len(articles) == 1
    assert articles[0]["image_url"] == "https://cdn.example.com/photo.jpg"
    assert articles[0]["image_source"] == "media_content"


def test_parse_feed_extracts_enclosure_image() -> None:
    """Parse RSS with image enclosure extracts image_url and image_source."""
    articles = parse_feed(RSS_WITH_ENCLOSURE)
    assert len(articles) == 1
    assert articles[0]["image_url"] == "https://cdn.example.com/thumb.png"
    assert articles[0]["image_source"] == "enclosure"


def test_parse_feed_extracts_img_from_content() -> None:
    """Parse RSS with img in content:encoded extracts image_url and image_source."""
    articles = parse_feed(RSS_WITH_IMG_IN_CONTENT)
    assert len(articles) == 1
    assert articles[0]["image_url"] == "https://example.com/lead.jpg"
    assert articles[0]["image_source"] == "content_html"


RSS_THUMB_AND_CONTENT_IMG = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:media="http://search.yahoo.com/mrss/"
     xmlns:content="http://purl.org/rss/1.0/modules/content/">
<channel>
    <title>Mixed</title>
    <item>
        <title>Story</title>
        <link>https://example.com/story</link>
        <description>Summary</description>
        <media:thumbnail url="https://example.com/generic-thumb.jpg" width="120"/>
        <content:encoded><![CDATA[<p>Lead</p>
        <img src="https://example.com/article-lead.jpg" />]]></content:encoded>
        <pubDate>Mon, 01 Jan 2024 12:00:00 GMT</pubDate>
    </item>
</channel>
</rss>"""


def test_parse_feed_prefers_content_img_over_media_thumbnail() -> None:
    """In-item img in content beats media:thumbnail (often unrelated)."""
    articles = parse_feed(RSS_THUMB_AND_CONTENT_IMG)
    assert len(articles) == 1
    assert articles[0]["image_url"] == "https://example.com/article-lead.jpg"
    assert articles[0]["image_source"] == "content_html"


RSS_WITH_CATEGORIES = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
<channel>
    <title>Category Feed</title>
    <item>
        <title>Sports Article</title>
        <link>https://example.com/sports</link>
        <description>Summary</description>
        <category>Deportes</category>
        <category>Futbol</category>
        <pubDate>Mon, 01 Jan 2024 12:00:00 GMT</pubDate>
    </item>
    <item>
        <title>Politics Article</title>
        <link>https://example.com/politics</link>
        <description>Summary</description>
        <category>Politica</category>
        <pubDate>Tue, 02 Jan 2024 12:00:00 GMT</pubDate>
    </item>
    <item>
        <title>No Category</title>
        <link>https://example.com/none</link>
        <description>Summary</description>
        <pubDate>Wed, 03 Jan 2024 12:00:00 GMT</pubDate>
    </item>
</channel>
</rss>"""


def test_parse_feed_extracts_and_normalizes_categories() -> None:
    """Parse RSS with category tags extracts and normalizes to canonical IDs."""
    articles = parse_feed(RSS_WITH_CATEGORIES)
    assert len(articles) == 3
    assert articles[0]["categories"] == ["sports"]
    assert articles[1]["categories"] == ["politics"]
    assert articles[2]["categories"] == []
