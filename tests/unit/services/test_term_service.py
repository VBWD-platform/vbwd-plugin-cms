"""Unit tests for TermService (S47.0) — MagicMock repos, no DB."""
import datetime
from uuid import uuid4
from unittest.mock import MagicMock

import pytest

from plugins.cms.src.models.cms_term import CmsTerm
from plugins.cms.src.services.term_service import (
    TermService,
    TermNotFoundError,
    TermSlugConflictError,
    UnknownTermTypeError,
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


def _term(term_type="category", slug="news", name="News"):
    term = CmsTerm()
    term.id = uuid4()
    term.term_type = term_type
    term.slug = slug
    term.name = name
    term.sort_order = 0
    term.created_at = term.updated_at = datetime.datetime.utcnow()
    return term


def _make_service(terms=None):
    store = {str(t.id): t for t in (terms or [])}
    repo = MagicMock()
    repo.find_by_id.side_effect = lambda tid: store.get(str(tid))
    repo.find_by_type_and_slug.side_effect = lambda ttype, slug: next(
        (t for t in store.values() if t.term_type == ttype and t.slug == slug), None
    )
    repo.save.side_effect = lambda t: store.setdefault(str(t.id), t)
    return TermService(repo), repo, store


class TestCreateTerm:
    def test_unknown_term_type_fails_fast(self):
        service, _, _ = _make_service()
        with pytest.raises(UnknownTermTypeError):
            service.create_term({"term_type": "series", "name": "Saga"})

    def test_create_auto_slugifies_name(self):
        service, repo, _ = _make_service()
        service.create_term({"term_type": "tag", "name": "Big News"})
        assert repo.save.call_args[0][0].slug == "big-news"

    def test_duplicate_slug_within_type_conflicts(self):
        existing = _term(term_type="tag", slug="big-news")
        service, _, _ = _make_service(terms=[existing])
        with pytest.raises(TermSlugConflictError):
            service.create_term({"term_type": "tag", "name": "Big News"})

    def test_same_slug_different_type_allowed(self):
        existing = _term(term_type="category", slug="news")
        service, repo, _ = _make_service(terms=[existing])
        service.create_term({"term_type": "tag", "name": "News"})
        repo.save.assert_called_once()


class TestUpdateDeleteTerm:
    def test_update_missing_raises(self):
        service, _, _ = _make_service()
        with pytest.raises(TermNotFoundError):
            service.update_term(str(uuid4()), {"name": "X"})

    def test_update_name(self):
        term = _term()
        service, _, _ = _make_service(terms=[term])
        assert service.update_term(str(term.id), {"name": "Headlines"})["name"] == (
            "Headlines"
        )

    def test_delete_missing_raises(self):
        service, _, _ = _make_service()
        with pytest.raises(TermNotFoundError):
            service.delete_term(str(uuid4()))

    def test_delete_calls_repo(self):
        term = _term()
        service, repo, _ = _make_service(terms=[term])
        service.delete_term(str(term.id))
        repo.delete.assert_called_once_with(str(term.id))
