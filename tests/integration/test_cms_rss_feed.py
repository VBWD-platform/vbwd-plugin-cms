"""Integration tests for the RSS feed route (S47.5, real PG + the live app).

Exercises ``GET /api/v1/cms/rss.xml`` against a seeded corpus through the real
blueprint, PostService and PostRepository:
  - correct content-type + a valid RSS 2.0 document;
  - published-only, newest-first items;
  - ``?term_type=&term_slug=`` narrows to one taxonomy term;
  - an unknown term yields an empty but valid channel (not a 500).

Posts are seeded through PostService (never raw SQL), mirroring the FTS suite.
"""
import uuid
from datetime import datetime, timedelta, timezone
from xml.etree import ElementTree

import pytest

from plugins.cms.src.models.cms_post import POST_STATUS_PUBLISHED, POST_STATUS_DRAFT
from plugins.cms.src.repositories.post_repository import PostRepository
from plugins.cms.src.repositories.term_repository import TermRepository
from plugins.cms.src.repositories.post_term_repository import PostTermRepository
from plugins.cms.src.services.post_service import PostService
from plugins.cms.src.services.term_service import TermService
from plugins.cms.src.services import post_type_registry, term_type_registry
from plugins.cms.src.services.post_type_registry import PostType
from plugins.cms.src.services.term_type_registry import TermType


@pytest.fixture(autouse=True)
def _registries():
    post_type_registry.clear_post_types()
    post_type_registry.register_post_type(
        PostType(key="post", label="Post", routable=True, hierarchical=False)
    )
    term_type_registry.clear_term_types()
    term_type_registry.register_term_type(
        TermType(key="category", label="Category", hierarchical=True)
    )
    yield
    post_type_registry.clear_post_types()
    term_type_registry.clear_term_types()


def _post_service(db):
    return PostService(
        repo=PostRepository(db.session),
        term_repo=TermRepository(db.session),
        post_term_repo=PostTermRepository(db.session),
        event_dispatcher=None,
    )


@pytest.fixture
def seeded(db):
    marker = uuid.uuid4().hex[:8]
    post_service = _post_service(db)
    term_service = TermService(TermRepository(db.session))

    news = term_service.create_term(
        {"term_type": "category", "name": "News", "slug": f"news-{marker}"}
    )

    older = post_service.create_post(
        {
            "type": "post",
            "title": f"Older post {marker}",
            "slug": f"older-{marker}",
            "excerpt": "older excerpt",
            "status": POST_STATUS_PUBLISHED,
        }
    )
    newer = post_service.create_post(
        {
            "type": "post",
            "title": f"Newer post {marker}",
            "slug": f"newer-{marker}",
            "excerpt": "newer excerpt",
            "status": POST_STATUS_PUBLISHED,
        }
    )
    draft = post_service.create_post(
        {
            "type": "post",
            "title": f"Draft post {marker}",
            "slug": f"draft-{marker}",
            "status": POST_STATUS_DRAFT,
        }
    )

    # Force a deterministic published_at ordering (newer is strictly newer).
    repo = PostRepository(db.session)
    base = datetime(2026, 5, 1, 12, 0, 0, tzinfo=timezone.utc)
    older_row = repo.find_by_id(older["id"])
    older_row.published_at = base
    repo.save(older_row)
    newer_row = repo.find_by_id(newer["id"])
    newer_row.published_at = base + timedelta(days=1)
    repo.save(newer_row)

    post_service.assign_terms(newer["id"], [news["id"]])

    return {
        "marker": marker,
        "older": older,
        "newer": newer,
        "draft": draft,
        "news_slug": f"news-{marker}",
    }


def _channel(resp):
    root = ElementTree.fromstring(resp.data)
    assert root.tag == "rss"
    assert root.attrib.get("version") == "2.0"
    channel = root.find("channel")
    assert channel is not None
    return channel


def _item_titles(channel):
    return [item.findtext("title") for item in channel.findall("item")]


class TestContentType:
    def test_content_type_is_rss(self, client, db, seeded):
        resp = client.get("/api/v1/cms/rss.xml")
        assert resp.status_code == 200
        assert resp.content_type.startswith("application/rss+xml")
        assert "charset=utf-8" in resp.content_type


class TestWholeBlog:
    def test_returns_published_posts_only(self, client, db, seeded):
        channel = _channel(client.get("/api/v1/cms/rss.xml"))
        titles = _item_titles(channel)
        assert seeded["newer"]["title"] in titles
        assert seeded["older"]["title"] in titles
        assert seeded["draft"]["title"] not in titles

    def test_newest_first_ordering(self, client, db, seeded):
        channel = _channel(client.get("/api/v1/cms/rss.xml"))
        titles = _item_titles(channel)
        newer_index = titles.index(seeded["newer"]["title"])
        older_index = titles.index(seeded["older"]["title"])
        assert newer_index < older_index


class TestTermFilter:
    def test_term_filter_narrows(self, client, db, seeded):
        resp = client.get(
            "/api/v1/cms/rss.xml"
            f"?type=post&term_type=category&term_slug={seeded['news_slug']}"
        )
        channel = _channel(resp)
        titles = _item_titles(channel)
        assert seeded["newer"]["title"] in titles
        assert seeded["older"]["title"] not in titles


class TestUnknownTerm:
    def test_unknown_term_returns_empty_valid_channel(self, client, db, seeded):
        resp = client.get(
            "/api/v1/cms/rss.xml?type=post&term_type=category&term_slug=does-not-exist"
        )
        assert resp.status_code == 200
        assert resp.content_type.startswith("application/rss+xml")
        channel = _channel(resp)
        assert channel.findtext("title")
        assert channel.find("item") is None
