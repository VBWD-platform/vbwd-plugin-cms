"""Unit tests for TermImportExportService (taxonomy round-trip).

MagicMock repo, no DB. Exercises the VBWD-standard JSON envelope on export and
the natural-key ``(term_type, slug)`` upsert + ``parent_slug`` resolution on
import. Engineering requirements (binding, restated): TDD-first (this is the RED
set); DevOps-first (no DB, runs cold local + CI); SOLID (one service, narrow
deps); DI (repo injected); DRY (reuses ``CmsTerm.to_dict()`` shape); Liskov;
clean code; no overengineering. Quality guard: ``bin/pre-commit-check.sh
--plugin cms --full``.
"""
import datetime
from uuid import uuid4
from unittest.mock import MagicMock

import pytest

from plugins.cms.src.models.cms_term import CmsTerm
from plugins.cms.src.services.term_import_export_service import (
    TermImportExportService,
    TermImportError,
)
from plugins.cms.src.services.term_type_registry import (
    TermType,
    register_term_type,
    clear_term_types,
)


@pytest.fixture(autouse=True)
def _registry():
    clear_term_types()
    register_term_type(TermType(key="category", label="Category", hierarchical=True))
    register_term_type(TermType(key="tag", label="Tag", hierarchical=False))
    yield
    clear_term_types()


def _term(term_type="category", slug="news", name="News", parent=None, **kw):
    term = CmsTerm()
    term.id = uuid4()
    term.term_type = term_type
    term.slug = slug
    term.name = name
    term.parent_id = parent.id if parent else None
    term.description = kw.get("description")
    term.seo_excluded = kw.get("seo_excluded", False)
    term.sort_order = kw.get("sort_order", 0)
    term.created_at = term.updated_at = datetime.datetime.utcnow()
    return term


def _make_service(terms=None):
    """A MagicMock repo backed by an in-memory dict, mirroring the real repo."""
    store = {str(t.id): t for t in (terms or [])}
    repo = MagicMock()
    repo.find_all.side_effect = lambda: list(store.values())
    repo.find_by_type.side_effect = lambda ttype: [
        t for t in store.values() if t.term_type == ttype
    ]
    repo.find_by_id.side_effect = lambda tid: store.get(str(tid))
    repo.find_by_type_and_slug.side_effect = lambda ttype, slug: next(
        (t for t in store.values() if t.term_type == ttype and t.slug == slug), None
    )

    def _save(term):
        if not getattr(term, "id", None):
            term.id = uuid4()
        store[str(term.id)] = term
        return term

    repo.save.side_effect = _save
    return TermImportExportService(repo), repo, store


class TestExport:
    def test_envelope_shape(self):
        service, _, _ = _make_service(terms=[_term()])
        payload = service.export_terms()
        assert payload["version"] == 1
        assert payload["entity"] == "cms_term"
        assert "exported_at" in payload
        assert isinstance(payload["items"], list)

    def test_item_fields_include_parent_slug(self):
        parent = _term(slug="world", name="World")
        child = _term(slug="europe", name="Europe", parent=parent)
        service, _, _ = _make_service(terms=[parent, child])
        items = {item["slug"]: item for item in service.export_terms()["items"]}
        assert items["world"]["parent_slug"] is None
        assert items["europe"]["parent_slug"] == "world"
        for key in (
            "term_type",
            "slug",
            "name",
            "parent_slug",
            "description",
            "seo_excluded",
            "sort_order",
        ):
            assert key in items["europe"]
        # No internal ids leak into the portable envelope.
        assert "id" not in items["europe"]
        assert "parent_id" not in items["europe"]

    def test_type_filter_only_exports_that_type(self):
        service, _, _ = _make_service(
            terms=[
                _term(term_type="category", slug="news"),
                _term(term_type="tag", slug="hot"),
            ]
        )
        items = service.export_terms(term_type="tag")["items"]
        assert [item["slug"] for item in items] == ["hot"]


class TestImport:
    def _payload(self, items):
        return {
            "version": 1,
            "entity": "cms_term",
            "items": items,
        }

    def test_import_creates_new_terms(self):
        service, _, store = _make_service()
        result = service.import_terms(
            self._payload([{"term_type": "tag", "slug": "hot", "name": "Hot"}])
        )
        assert result == {"created": 1, "updated": 0}
        assert any(t.slug == "hot" for t in store.values())

    def test_reimport_is_idempotent(self):
        service, _, _ = _make_service()
        payload = self._payload([{"term_type": "tag", "slug": "hot", "name": "Hot"}])
        service.import_terms(payload)
        second = service.import_terms(payload)
        assert second == {"created": 0, "updated": 1}

    def test_upsert_updates_existing_by_natural_key(self):
        existing = _term(term_type="tag", slug="hot", name="Hot")
        service, _, store = _make_service(terms=[existing])
        service.import_terms(
            self._payload([{"term_type": "tag", "slug": "hot", "name": "Trending"}])
        )
        assert store[str(existing.id)].name == "Trending"

    def test_parent_slug_resolves_within_type(self):
        service, _, store = _make_service()
        service.import_terms(
            self._payload(
                [
                    {
                        "term_type": "category",
                        "slug": "europe",
                        "name": "Europe",
                        "parent_slug": "world",
                    },
                    {"term_type": "category", "slug": "world", "name": "World"},
                ]
            )
        )
        by_slug = {t.slug: t for t in store.values()}
        assert by_slug["europe"].parent_id == by_slug["world"].id

    def test_unknown_term_type_rejected(self):
        service, _, _ = _make_service()
        with pytest.raises(TermImportError):
            service.import_terms(
                self._payload([{"term_type": "series", "slug": "saga", "name": "Saga"}])
            )

    def test_round_trip_reproduces_the_term_set(self):
        parent = _term(slug="world", name="World")
        child = _term(slug="europe", name="Europe", parent=parent)
        source, _, _ = _make_service(terms=[parent, child])
        exported = source.export_terms()

        target, _, store = _make_service()
        target.import_terms(exported)

        produced = {(t.term_type, t.slug) for t in store.values()}
        assert produced == {("category", "world"), ("category", "europe")}
        by_slug = {t.slug: t for t in store.values()}
        assert by_slug["europe"].parent_id == by_slug["world"].id
