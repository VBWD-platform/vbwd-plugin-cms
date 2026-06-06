"""Unit: PostImportExportService — VBWD-standard posts export/import.

MagicMock repos, no DB. Mirrors the R1 TermImportExportService pattern: a
portable, id-free JSON envelope keyed by the natural key ``(type, slug)`` with
layout/style/parent/term references resolved by slug. Export resolves
layout_id/style_id/parent_id → slugs and lists term refs (term_type + slug);
import upserts by (type, slug), is idempotent, and resolves refs by slug.

Engineering requirements (binding, restated): TDD-first; SOLID (single
responsibility: export/import only; CRUD stays in PostService); DI (repos
injected); DRY (one envelope shape, mirrors terms IO); no overengineering.
Quality guard: ``bin/pre-commit-check.sh --plugin cms --full``.
"""
from uuid import uuid4
from unittest.mock import MagicMock

import pytest

from plugins.cms.src.models.cms_post import CmsPost
from plugins.cms.src.services.post_import_export_service import (
    PostImportExportService,
    PostImportError,
    ENVELOPE_ENTITY,
    ENVELOPE_VERSION,
)
from plugins.cms.src.services.post_type_registry import (
    PostType,
    register_post_type,
    clear_post_types,
)


@pytest.fixture(autouse=True)
def _registry():
    clear_post_types()
    register_post_type(
        PostType(key="page", label="Page", routable=True, hierarchical=True)
    )
    register_post_type(
        PostType(key="post", label="Post", routable=True, hierarchical=False)
    )
    yield
    clear_post_types()


class _FakePostRepo:
    """In-memory post store keyed by (type, slug); ids assigned on save."""

    def __init__(self):
        self._by_id = {}

    def add(self, post):
        post.id = post.id or uuid4()
        self._by_id[str(post.id)] = post

    def find_by_id(self, post_id):
        return self._by_id.get(str(post_id))

    def find_by_type_and_slug(self, post_type, slug):
        return next(
            (p for p in self._by_id.values() if p.type == post_type and p.slug == slug),
            None,
        )

    def find_paginated(self, post_type=None, per_page=20, **kwargs):
        items = [
            p for p in self._by_id.values() if post_type is None or p.type == post_type
        ]
        return {"items": items, "total": len(items)}

    def save(self, post):
        post.id = post.id or uuid4()
        self._by_id[str(post.id)] = post
        return post


class _FakeRefRepo:
    """Slug↔id store for layouts / styles."""

    def __init__(self):
        self._by_id = {}
        self._by_slug = {}

    def add(self, slug):
        obj = MagicMock()
        obj.id = uuid4()
        obj.slug = slug
        self._by_id[str(obj.id)] = obj
        self._by_slug[slug] = obj
        return obj

    def find_by_id(self, obj_id):
        return self._by_id.get(str(obj_id))

    def find_by_slug(self, slug):
        return self._by_slug.get(slug)


class _FakeTermRepo:
    def __init__(self):
        self._by_id = {}
        self._by_key = {}

    def add(self, term_type, slug):
        term = MagicMock()
        term.id = uuid4()
        term.term_type = term_type
        term.slug = slug
        self._by_id[str(term.id)] = term
        self._by_key[(term_type, slug)] = term
        return term

    def find_by_id(self, term_id):
        return self._by_id.get(str(term_id))

    def find_by_type_and_slug(self, term_type, slug):
        return self._by_key.get((term_type, slug))


class _FakePostTermRepo:
    def __init__(self):
        self._by_post = {}

    def find_by_post(self, post_id):
        return self._by_post.get(str(post_id), [])

    def replace_for_post(self, post_id, term_ids):
        links = []
        for term_id in term_ids:
            link = MagicMock()
            link.post_id = post_id
            link.term_id = term_id
            links.append(link)
        self._by_post[str(post_id)] = links
        return links


def _new_post(post_repo, **kwargs):
    post = CmsPost()
    post.id = uuid4()
    post.type = kwargs.get("type", "post")
    post.slug = kwargs["slug"]
    post.title = kwargs.get("title", kwargs["slug"].title())
    post.excerpt = kwargs.get("excerpt")
    post.content_json = kwargs.get("content_json") or {}
    post.content_html = kwargs.get("content_html")
    post.source_css = kwargs.get("source_css")
    post.status = kwargs.get("status", "draft")
    post.language = "en"
    post.sort_order = 0
    post.layout_id = kwargs.get("layout_id")
    post.style_id = kwargs.get("style_id")
    post.parent_id = kwargs.get("parent_id")
    post.meta_title = kwargs.get("meta_title")
    post_repo.add(post)
    return post


def _make_service():
    post_repo = _FakePostRepo()
    layout_repo = _FakeRefRepo()
    style_repo = _FakeRefRepo()
    term_repo = _FakeTermRepo()
    post_term_repo = _FakePostTermRepo()
    service = PostImportExportService(
        post_repo=post_repo,
        layout_repo=layout_repo,
        style_repo=style_repo,
        term_repo=term_repo,
        post_term_repo=post_term_repo,
    )
    return service, post_repo, layout_repo, style_repo, term_repo, post_term_repo


class TestExport:
    def test_envelope_shape(self):
        service, post_repo, layout_repo, style_repo, _, _ = _make_service()
        layout = layout_repo.add("magazine")
        style = style_repo.add("dark")
        _new_post(
            post_repo,
            type="post",
            slug="hello",
            title="Hello",
            layout_id=layout.id,
            style_id=style.id,
        )
        payload = service.export_posts()
        assert payload["version"] == ENVELOPE_VERSION
        assert payload["entity"] == ENVELOPE_ENTITY
        item = payload["items"][0]
        assert item["type"] == "post"
        assert item["slug"] == "hello"
        assert item["layout_slug"] == "magazine"
        assert item["style_slug"] == "dark"
        assert "use_theme_switcher_styles" not in item
        assert item["parent_slug"] is None
        assert item["terms"] == []

    def test_export_includes_parent_and_terms(self):
        service, post_repo, _, _, term_repo, post_term_repo = _make_service()
        parent = _new_post(post_repo, type="page", slug="about", title="About")
        child = _new_post(
            post_repo,
            type="page",
            slug="about/team",
            title="Team",
            parent_id=parent.id,
        )
        category = term_repo.add("category", "news")
        post_term_repo.replace_for_post(str(child.id), [str(category.id)])

        items = {i["slug"]: i for i in service.export_posts()["items"]}
        assert items["about/team"]["parent_slug"] == "about"
        assert {"term_type": "category", "slug": "news"} in items["about/team"]["terms"]

    def test_export_type_filter(self):
        service, post_repo, _, _, _, _ = _make_service()
        _new_post(post_repo, type="page", slug="home")
        _new_post(post_repo, type="post", slug="hello")
        slugs = [i["slug"] for i in service.export_posts(post_type="post")["items"]]
        assert slugs == ["hello"]


class TestImport:
    def _payload(self, **overrides):
        item = {
            "type": "post",
            "slug": "hello",
            "title": "Hello",
            "excerpt": "x",
            "content_html": "<p>hi</p>",
            "content_json": {},
            "status": "published",
            "layout_slug": None,
            "style_slug": None,
            "parent_slug": None,
            "terms": [],
        }
        item.update(overrides)
        return {"version": ENVELOPE_VERSION, "entity": ENVELOPE_ENTITY, "items": [item]}

    def test_import_creates_then_idempotent(self):
        service, post_repo, _, _, _, _ = _make_service()
        first = service.import_posts(self._payload())
        assert first == {"created": 1, "updated": 0}
        assert post_repo.find_by_type_and_slug("post", "hello") is not None

        second = service.import_posts(self._payload())
        assert second == {"created": 0, "updated": 1}

    def test_import_accepts_single_object_not_wrapped(self):
        # A one-item export (no envelope) imports as readily as a bundle.
        service, post_repo, _, _, _, _ = _make_service()
        result = service.import_posts(
            {"type": "page", "slug": "about", "title": "About"}
        )
        assert result == {"created": 1, "updated": 0}
        assert post_repo.find_by_type_and_slug("page", "about") is not None

    def test_import_accepts_bare_list(self):
        service, post_repo, _, _, _, _ = _make_service()
        result = service.import_posts([{"type": "page", "slug": "a", "title": "A"}])
        assert result == {"created": 1, "updated": 0}

    def test_import_preserves_existing_status_when_absent(self):
        # Re-importing must not demote a published post to draft.
        service, post_repo, _, _, _, _ = _make_service()
        _new_post(post_repo, type="page", slug="home", title="Home", status="published")
        service.import_posts(
            {"type": "page", "slug": "home", "title": "Home"}  # no status key
        )
        assert post_repo.find_by_type_and_slug("page", "home").status == "published"

    def test_import_maps_legacy_is_published(self):
        service, post_repo, _, _, _, _ = _make_service()
        service.import_posts(
            {"type": "page", "slug": "p", "name": "P", "is_published": True}
        )
        assert post_repo.find_by_type_and_slug("page", "p").status == "published"

    def test_new_post_without_status_defaults_draft(self):
        service, post_repo, _, _, _, _ = _make_service()
        service.import_posts({"type": "page", "slug": "fresh", "title": "Fresh"})
        assert post_repo.find_by_type_and_slug("page", "fresh").status == "draft"

    def test_source_css_round_trips(self):
        service, post_repo, _, _, _, _ = _make_service()
        _new_post(post_repo, type="post", slug="styled", title="Styled",
                  source_css=".x{color:red}")
        item = service.export_posts(post_type="post")["items"][0]
        assert item["source_css"] == ".x{color:red}"
        # import into a fresh service applies it
        service2, repo2, _, _, _, _ = _make_service()
        service2.import_posts({"items": [item]})
        assert repo2.find_by_type_and_slug("post", "styled").source_css == ".x{color:red}"

    def test_import_uses_name_when_title_missing(self):
        # Legacy cms_page exports carry `name`, not `title`.
        service, post_repo, _, _, _, _ = _make_service()
        service.import_posts({"type": "page", "slug": "legacy", "name": "Legacy Page"})
        post = post_repo.find_by_type_and_slug("page", "legacy")
        assert post.title == "Legacy Page"

    def test_import_resolves_layout_style_by_slug(self):
        service, post_repo, layout_repo, style_repo, _, _ = _make_service()
        layout = layout_repo.add("magazine")
        style = style_repo.add("dark")
        service.import_posts(self._payload(layout_slug="magazine", style_slug="dark"))
        post = post_repo.find_by_type_and_slug("post", "hello")
        assert str(post.layout_id) == str(layout.id)
        assert str(post.style_id) == str(style.id)

    def test_import_unknown_layout_slug_leaves_null(self):
        service, post_repo, _, _, _, _ = _make_service()
        service.import_posts(self._payload(layout_slug="ghost"))
        post = post_repo.find_by_type_and_slug("post", "hello")
        assert post.layout_id is None

    def test_import_resolves_parent_and_terms_by_slug(self):
        service, post_repo, _, _, term_repo, post_term_repo = _make_service()
        term_repo.add("category", "news")
        payload = {
            "version": ENVELOPE_VERSION,
            "entity": ENVELOPE_ENTITY,
            "items": [
                {"type": "page", "slug": "about", "title": "About"},
                {
                    "type": "page",
                    "slug": "about/team",
                    "title": "Team",
                    "parent_slug": "about",
                    "terms": [{"term_type": "category", "slug": "news"}],
                },
            ],
        }
        result = service.import_posts(payload)
        assert result == {"created": 2, "updated": 0}
        parent = post_repo.find_by_type_and_slug("page", "about")
        child = post_repo.find_by_type_and_slug("page", "about/team")
        assert str(child.parent_id) == str(parent.id)
        links = post_term_repo.find_by_post(str(child.id))
        assert len(links) == 1

    def test_import_bad_payload_raises(self):
        service, _, _, _, _, _ = _make_service()
        with pytest.raises(PostImportError):
            service.import_posts({"items": "nope"})

    def test_import_unknown_type_raises(self):
        service, _, _, _, _, _ = _make_service()
        with pytest.raises(PostImportError):
            service.import_posts(
                {"items": [{"type": "ghost", "slug": "x", "title": "X"}]}
            )

    def test_round_trip_reproduces_set(self):
        (
            service,
            post_repo,
            layout_repo,
            style_repo,
            term_repo,
            post_term_repo,
        ) = _make_service()
        layout = layout_repo.add("magazine")
        category = term_repo.add("category", "news")
        post = _new_post(
            post_repo,
            type="post",
            slug="hello",
            title="Hello",
            layout_id=layout.id,
        )
        post_term_repo.replace_for_post(str(post.id), [str(category.id)])

        exported = service.export_posts()

        # Fresh target environment with the same layout/term slugs present.
        target, target_posts, target_layouts, _, target_terms, _ = _make_service()
        target_layouts.add("magazine")
        target_terms.add("category", "news")
        result = target.import_posts(exported)
        assert result["created"] == 1
        reimported = target_posts.find_by_type_and_slug("post", "hello")
        assert reimported.title == "Hello"
        assert str(reimported.layout_id) == str(
            target_layouts.find_by_slug("magazine").id
        )
