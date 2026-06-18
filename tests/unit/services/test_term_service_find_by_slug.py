"""S91 Slice 1 — TermService.find_by_slug (public slug lookup for the embed manifest).

The embed-manifest route resolves a category by slug to validate a device's
configuration. The route must not reach into the repository directly (route →
service → repo layering), so TermService exposes a public ``find_by_slug`` that
returns the term's ``to_dict()`` or ``None`` when no term matches.

Engineering requirements (binding, restated): TDD-first; DevOps-first; SOLID/
DI/DRY (one home for the by-slug lookup, delegating to the repo's existing
``find_by_type_and_slug``); Liskov (absence is a clean ``None``, not a raise);
clean code; no overengineering. Quality guard:
``bin/pre-commit-check.sh --plugin cms --full``.
"""
import datetime
from unittest.mock import MagicMock
from uuid import uuid4

from plugins.cms.src.models.cms_term import CmsTerm
from plugins.cms.src.services.term_service import TermService


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
    store = {(t.term_type, t.slug): t for t in (terms or [])}
    repo = MagicMock()
    repo.find_by_type_and_slug.side_effect = lambda term_type, slug: store.get(
        (term_type, slug)
    )
    return TermService(repo), repo


def test_find_by_slug_returns_term_dict_when_present():
    existing = _term(term_type="category", slug="news", name="News")
    service, repo = _service([existing])

    result = service.find_by_slug("category", "news")

    assert result is not None
    assert result["id"] == str(existing.id)
    assert result["slug"] == "news"
    assert result["name"] == "News"
    repo.find_by_type_and_slug.assert_called_once_with("category", "news")


def test_find_by_slug_returns_none_when_absent():
    service, repo = _service([])

    result = service.find_by_slug("category", "missing")

    assert result is None
    repo.find_by_type_and_slug.assert_called_once_with("category", "missing")
