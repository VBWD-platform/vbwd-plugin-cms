"""Unit tests for RssFeedService (S47.5) — fake PostService, no DB.

The feed service reuses the 47.0/47.4 post-query (PostService.list_posts /
list_posts_by_term, published-only, newest-first, capped) and serializes the
returned summary dicts into a valid RSS 2.0 document with a real XML
serializer. These tests:
  - parse the produced XML back and validate the RSS 2.0 structure;
  - assert published-only / newest-first / capped delegation to the post query;
  - assert per-term filtering routes through list_posts_by_term;
  - assert absolute item links + permalink guids (from canonical_url);
  - assert RFC-822 pubDate from published_at;
  - assert XML escaping of special characters in titles/descriptions.
"""
from xml.etree import ElementTree

from plugins.cms.src.models.cms_post import POST_STATUS_PUBLISHED
from plugins.cms.src.services.rss_feed_service import RssFeedService


PUBLIC_BASE_URL = "https://example.com"


def _summary(
    *,
    slug="hello-world",
    title="Hello World",
    excerpt="An excerpt",
    content_html=None,
    canonical_url="https://example.com/hello-world",
    published_at="2026-05-01T09:30:00+00:00",
    post_type="post",
):
    return {
        "slug": slug,
        "title": title,
        "excerpt": excerpt,
        "content_html": content_html,
        "meta_description": None,
        "canonical_url": canonical_url,
        "published_at": published_at,
        "type": post_type,
        "status": POST_STATUS_PUBLISHED,
    }


class _FakePostService:
    """Honours the narrow PostService surface the feed depends on.

    Records the keyword arguments it was called with so tests can assert the
    feed delegates the published-only / newest-first / capped query (DRY) and
    routes the per-term case through list_posts_by_term.
    """

    def __init__(self, items=None):
        self._items = items if items is not None else []
        self.list_posts_calls = []
        self.list_posts_by_term_calls = []

    def list_posts(self, **kwargs):
        self.list_posts_calls.append(kwargs)
        return self._page()

    def list_posts_by_term(self, **kwargs):
        self.list_posts_by_term_calls.append(kwargs)
        return self._page()

    def _page(self):
        return {
            "items": list(self._items),
            "total": len(self._items),
            "page": 1,
            "per_page": len(self._items) or 20,
            "pages": 1,
        }


def _build_service(items=None, item_limit=20):
    service = _FakePostService(items=items)
    feed = RssFeedService(
        post_service=service,
        public_base_url=PUBLIC_BASE_URL,
        item_limit=item_limit,
    )
    return feed, service


def _parse(xml_text):
    return ElementTree.fromstring(xml_text)


class TestRss2Structure:
    def test_root_is_rss_2_with_channel(self):
        feed, _ = _build_service(items=[_summary()])
        root = _parse(feed.build())
        assert root.tag == "rss"
        assert root.attrib.get("version") == "2.0"
        channel = root.find("channel")
        assert channel is not None

    def test_channel_has_required_elements(self):
        feed, _ = _build_service(items=[_summary()])
        channel = _parse(feed.build()).find("channel")
        assert channel.findtext("title")
        assert channel.findtext("link")
        assert channel.findtext("description") is not None
        assert channel.findtext("lastBuildDate")
        assert channel.findtext("language")

    def test_channel_link_is_the_public_base_url(self):
        feed, _ = _build_service(items=[_summary()])
        channel = _parse(feed.build()).find("channel")
        assert channel.findtext("link") == PUBLIC_BASE_URL

    def test_item_has_title_link_guid_pubdate_description(self):
        feed, _ = _build_service(items=[_summary()])
        item = _parse(feed.build()).find("channel/item")
        assert item is not None
        assert item.findtext("title") == "Hello World"
        assert item.findtext("link") == "https://example.com/hello-world"
        guid = item.find("guid")
        assert guid is not None
        assert guid.text == "https://example.com/hello-world"
        assert guid.attrib.get("isPermaLink") == "true"
        assert item.findtext("pubDate")
        assert item.findtext("description")


class TestPostQueryReuse:
    def test_whole_blog_delegates_published_only_newest_first_capped(self):
        feed, service = _build_service(items=[_summary()], item_limit=20)
        feed.build()
        assert len(service.list_posts_calls) == 1
        call = service.list_posts_calls[0]
        assert call["status"] == POST_STATUS_PUBLISHED
        assert call["newest_first"] is True
        assert call["per_page"] == 20
        assert call["page"] == 1
        assert service.list_posts_by_term_calls == []

    def test_item_limit_is_forwarded_as_per_page(self):
        feed, service = _build_service(items=[_summary()], item_limit=5)
        feed.build()
        assert service.list_posts_calls[0]["per_page"] == 5

    def test_post_type_is_forwarded(self):
        feed, service = _build_service(items=[_summary()])
        feed.build(post_type="post")
        assert service.list_posts_calls[0]["post_type"] == "post"

    def test_per_term_routes_through_list_posts_by_term(self):
        feed, service = _build_service(items=[_summary()])
        feed.build(term=("category", "news"))
        assert len(service.list_posts_by_term_calls) == 1
        call = service.list_posts_by_term_calls[0]
        assert call["term_type"] == "category"
        assert call["term_slug"] == "news"
        assert call["status"] == POST_STATUS_PUBLISHED
        assert call["newest_first"] is True
        assert service.list_posts_calls == []


class TestAbsoluteLinks:
    def test_item_link_uses_canonical_url_when_present(self):
        feed, _ = _build_service(
            items=[_summary(canonical_url="https://example.com/blog/post-a")]
        )
        item = _parse(feed.build()).find("channel/item")
        assert item.findtext("link") == "https://example.com/blog/post-a"

    def test_item_link_falls_back_to_base_url_plus_slug(self):
        feed, _ = _build_service(
            items=[_summary(canonical_url=None, slug="fallback-post")]
        )
        item = _parse(feed.build()).find("channel/item")
        assert item.findtext("link") == "https://example.com/fallback-post"


class TestPubDate:
    def test_pubdate_is_rfc_822(self):
        feed, _ = _build_service(
            items=[_summary(published_at="2026-05-01T09:30:00+00:00")]
        )
        item = _parse(feed.build()).find("channel/item")
        # RFC-822: "Fri, 01 May 2026 09:30:00 +0000"
        pub_date = item.findtext("pubDate")
        assert pub_date == "Fri, 01 May 2026 09:30:00 +0000"


class TestDescription:
    def test_description_prefers_excerpt(self):
        feed, _ = _build_service(
            items=[_summary(excerpt="My excerpt", content_html="<p>body</p>")]
        )
        item = _parse(feed.build()).find("channel/item")
        assert item.findtext("description") == "My excerpt"

    def test_description_falls_back_to_sanitized_html(self):
        feed, _ = _build_service(
            items=[
                _summary(
                    excerpt=None,
                    content_html="<p>Hello <b>world</b></p>",
                )
            ]
        )
        item = _parse(feed.build()).find("channel/item")
        description = item.findtext("description")
        assert "<" not in description
        assert "Hello world" in description


class TestEscaping:
    def test_special_chars_in_title_are_escaped_and_round_trip(self):
        nasty = "A & B <tag> \"q\" 'a'"
        feed, _ = _build_service(items=[_summary(title=nasty, excerpt="ok")])
        xml_text = feed.build()
        # No raw, unescaped ampersand-tag injection survived.
        assert "<tag>" not in xml_text
        # Parses back cleanly and the text round-trips.
        item = _parse(xml_text).find("channel/item")
        assert item.findtext("title") == nasty

    def test_special_chars_in_description_round_trip(self):
        nasty = "5 < 10 & 10 > 5"
        feed, _ = _build_service(items=[_summary(excerpt=nasty)])
        item = _parse(feed.build()).find("channel/item")
        assert item.findtext("description") == nasty


class TestEmptyFeed:
    def test_no_posts_still_valid_channel(self):
        feed, _ = _build_service(items=[])
        root = _parse(feed.build())
        channel = root.find("channel")
        assert channel is not None
        assert channel.findtext("title")
        assert channel.find("item") is None
