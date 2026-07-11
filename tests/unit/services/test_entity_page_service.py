"""Unit: EntityPageService — scaffold / save / public_view / delete (S128).

Exercises the service against in-memory fakes (no DB): an unlinked owner returns
an empty content+SEO scaffold; ``save`` resolve-or-creates an ``entity_page``
CmsPost through the post service and upserts the link; ``public_view`` projects
only a published post and never leaks the ORM object; ``delete_for_owner`` drops
the linked post(s) + link(s).

Engineering requirements (binding, restated): TDD-first; DevOps-first; SOLID
(SRP — the link is separate from the post); DI (collaborators injected, not
globals); DRY (one content home = CmsPost); Liskov (unlinked → scaffold /
None, never a crash); clean code; no overengineering. Quality guard:
``bin/pre-commit-check.sh --plugin cms --full``.
"""
import uuid

import pytest

from plugins.cms.src.services.entity_page_service import (
    EntityPageService,
    SEO_FIELD_NAMES,
    ENTITY_PAGE_POST_TYPE,
)
from plugins.cms.src.models.cms_post import POST_STATUS_PUBLISHED


class _FakePost:
    def __init__(self, data, post_id):
        self.id = post_id
        self.type = data.get("type")
        self.title = data.get("title")
        self.status = data.get("status") or POST_STATUS_PUBLISHED
        self.content_html = data.get("content_html")
        self.content_json = data.get("content_json") or {}
        self.source_css = data.get("source_css")
        for name in SEO_FIELD_NAMES:
            setattr(self, name, data.get(name))
        if self.robots is None:
            self.robots = "index,follow"
        if self.seo_excluded is None:
            self.seo_excluded = False

    def apply(self, data):
        for key, value in data.items():
            if key == "content_blocks":
                continue
            setattr(self, key, value)


class _FakeBlock:
    def __init__(self, data, post_id):
        self._data = {"post_id": post_id, **data}

    def to_dict(self):
        return dict(self._data)


class _Store:
    def __init__(self):
        self.posts = {}
        self.blocks = {}


class _FakePostService:
    def __init__(self, store):
        self.store = store
        self.create_calls = []
        self.update_calls = []
        self.delete_calls = []

    def create_post(self, data):
        post_id = str(uuid.uuid4())
        self.store.posts[post_id] = _FakePost(data, post_id)
        self.store.blocks[post_id] = list(data.get("content_blocks") or [])
        self.create_calls.append(data)
        return {"id": post_id}

    def update_post(self, post_id, data):
        self.store.posts[post_id].apply(data)
        if "content_blocks" in data:
            self.store.blocks[post_id] = list(data["content_blocks"])
        self.update_calls.append((post_id, data))
        return {"id": post_id}

    def delete_post(self, post_id):
        self.store.posts.pop(post_id, None)
        self.store.blocks.pop(post_id, None)
        self.delete_calls.append(post_id)


class _FakePostRepo:
    def __init__(self, store):
        self.store = store

    def find_by_id(self, post_id):
        return self.store.posts.get(post_id)


class _FakeContentBlockRepo:
    def __init__(self, store):
        self.store = store

    def find_by_post(self, post_id):
        return [
            _FakeBlock(data, post_id) for data in self.store.blocks.get(post_id, [])
        ]


class _FakeLink:
    def __init__(self, owner_type, owner_id, slot, post_id):
        self.owner_type = owner_type
        self.owner_id = owner_id
        self.slot = slot
        self.post_id = post_id


class _FakeEntityPageRepo:
    def __init__(self):
        self.links = {}

    def get_by_owner(self, owner_type, owner_id, slot="main"):
        return self.links.get((owner_type, str(owner_id), slot))

    def find_by_owner(self, owner_type, owner_id):
        return [
            link
            for key, link in self.links.items()
            if key[0] == owner_type and key[1] == str(owner_id)
        ]

    def upsert(self, owner_type, owner_id, slot, post_id):
        link = _FakeLink(owner_type, str(owner_id), slot, post_id)
        self.links[(owner_type, str(owner_id), slot)] = link
        return link

    def delete_by_owner(self, owner_type, owner_id):
        keys = [
            key
            for key in list(self.links)
            if key[0] == owner_type and key[1] == str(owner_id)
        ]
        for key in keys:
            del self.links[key]
        return len(keys)


@pytest.fixture
def store():
    return _Store()


@pytest.fixture
def entity_page_repo():
    return _FakeEntityPageRepo()


@pytest.fixture
def post_service(store):
    return _FakePostService(store)


@pytest.fixture
def service(store, post_service, entity_page_repo):
    return EntityPageService(
        post_service=post_service,
        entity_page_repo=entity_page_repo,
        post_repo=_FakePostRepo(store),
        content_block_repo=_FakeContentBlockRepo(store),
    )


class TestGetOrScaffold:
    def test_unlinked_returns_empty_scaffold_with_all_seo_keys(self, service):
        scaffold = service.get_or_scaffold("dataset", "owner-1")

        assert scaffold["content_html"] == ""
        assert scaffold["content_json"] == {}
        assert scaffold["source_css"] == ""
        assert scaffold["content_blocks"] == []
        seo = scaffold["seo"]
        assert set(seo.keys()) == set(SEO_FIELD_NAMES)
        assert seo["meta_title"] == ""
        assert seo["robots"] == "index,follow"
        assert seo["seo_excluded"] is False
        assert seo["schema_json"] is None

    def test_linked_projects_the_post(self, service, post_service):
        service.save(
            "dataset",
            "owner-1",
            "main",
            {
                "content_html": "<p>hi</p>",
                "source_css": ".x{color:red}",
                "seo": {"meta_title": "T", "meta_description": "D"},
            },
            actor=None,
        )
        projection = service.get_or_scaffold("dataset", "owner-1")
        assert projection["content_html"] == "<p>hi</p>"
        assert projection["source_css"] == ".x{color:red}"
        assert projection["seo"]["meta_title"] == "T"
        assert projection["seo"]["meta_description"] == "D"


class TestSave:
    def test_creates_entity_page_post_and_link(
        self, service, post_service, entity_page_repo
    ):
        service.save(
            "dataset", "owner-1", "main", {"content_html": "<p>a</p>"}, actor=None
        )

        assert len(post_service.create_calls) == 1
        created = post_service.create_calls[0]
        assert created["type"] == ENTITY_PAGE_POST_TYPE
        assert created["title"]  # non-empty (CmsPost requires it)
        assert created["status"] == POST_STATUS_PUBLISHED
        assert entity_page_repo.get_by_owner("dataset", "owner-1", "main") is not None

    def test_second_save_updates_not_recreates(self, service, post_service):
        service.save(
            "dataset", "owner-1", "main", {"content_html": "<p>a</p>"}, actor=None
        )
        service.save(
            "dataset", "owner-1", "main", {"content_html": "<p>b</p>"}, actor=None
        )

        assert len(post_service.create_calls) == 1
        assert len(post_service.update_calls) == 1
        assert (
            service.get_or_scaffold("dataset", "owner-1")["content_html"] == "<p>b</p>"
        )

    def test_persists_all_seo_fields_and_blocks(self, service):
        seo_input = {name: f"v-{name}" for name in SEO_FIELD_NAMES}
        seo_input["seo_excluded"] = True
        result = service.save(
            "dataset",
            "owner-1",
            "main",
            {
                "content_html": "<p>body</p>",
                "content_blocks": [
                    {"area_name": "extra", "content_html": "<p>more</p>"}
                ],
                "seo": seo_input,
            },
            actor=None,
        )

        for name in SEO_FIELD_NAMES:
            assert result["seo"][name] == seo_input[name]
        assert len(result["content_blocks"]) == 1
        assert result["content_blocks"][0]["area_name"] == "extra"

    def test_distinct_slots_are_independent_posts(self, service, post_service):
        service.save("dataset", "owner-1", "main", {"content_html": "M"}, actor=None)
        service.save("dataset", "owner-1", "hero", {"content_html": "H"}, actor=None)

        assert len(post_service.create_calls) == 2
        assert (
            service.get_or_scaffold("dataset", "owner-1", "main")["content_html"] == "M"
        )
        assert (
            service.get_or_scaffold("dataset", "owner-1", "hero")["content_html"] == "H"
        )


class TestPublicView:
    def test_none_when_unlinked(self, service):
        assert service.public_view("dataset", "owner-1") is None

    def test_none_when_not_published(self, service, store, post_service):
        service.save(
            "dataset",
            "owner-1",
            "main",
            {"content_html": "<p>x</p>"},
            actor=None,
        )
        # Force the underlying post to a non-published status.
        post_id = next(iter(store.posts))
        store.posts[post_id].status = "draft"
        assert service.public_view("dataset", "owner-1") is None

    def test_projects_published(self, service):
        service.save(
            "dataset",
            "owner-1",
            "main",
            {"content_html": "<p>live</p>", "seo": {"meta_title": "Live"}},
            actor=None,
        )
        view = service.public_view("dataset", "owner-1")
        assert view["content_html"] == "<p>live</p>"
        assert view["seo"]["meta_title"] == "Live"
        assert isinstance(view, dict)  # ORM object never leaves the service


class TestDeleteForOwner:
    def test_deletes_post_and_link(self, service, post_service, entity_page_repo):
        service.save("dataset", "owner-1", "main", {"content_html": "x"}, actor=None)
        service.save("dataset", "owner-1", "hero", {"content_html": "y"}, actor=None)

        service.delete_for_owner("dataset", "owner-1")

        assert len(post_service.delete_calls) == 2
        assert entity_page_repo.find_by_owner("dataset", "owner-1") == []
        assert service.get_or_scaffold("dataset", "owner-1")["content_html"] == ""
