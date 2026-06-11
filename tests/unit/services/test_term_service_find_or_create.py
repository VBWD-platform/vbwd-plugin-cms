"""S52.8 — TermService.find_or_create (single home for term resolution).

Find-or-create by name (slug derived from name); returns the existing term
when one already matches the derived (term_type, slug) — never a duplicate.
"""
import datetime
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from plugins.cms.src.models.cms_term import CmsTerm
from plugins.cms.src.services.term_service import TermService
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


def _service(terms=None):
    store = {str(t.id): t for t in (terms or [])}
    repo = MagicMock()
    repo.find_by_id.side_effect = lambda tid: store.get(str(tid))
    repo.find_by_type_and_slug.side_effect = lambda ttype, slug: next(
        (t for t in store.values() if t.term_type == ttype and t.slug == slug), None
    )
    repo.save.side_effect = lambda t: store.setdefault(str(t.id), t)
    return TermService(repo), repo, store


def test_creates_when_absent():
    service, repo, store = _service()

    result = service.find_or_create("category", "News")

    assert result["name"] == "News"
    assert result["slug"] == "news"
    assert len(store) == 1


def test_returns_existing_when_present_no_duplicate():
    existing = _term(term_type="category", slug="news", name="News")
    service, repo, store = _service([existing])

    result = service.find_or_create("category", "News")

    assert result["id"] == str(existing.id)
    assert len(store) == 1
