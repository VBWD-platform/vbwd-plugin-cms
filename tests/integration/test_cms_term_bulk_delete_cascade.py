"""Integration guard: TermService.bulk_delete cascades the junction (real PG).

When an admin bulk-deletes taxonomy terms (categories/tags) from the term
manager, the term↔post association rows in ``cms_post_term`` must disappear
with the term (DB-level ``ondelete=CASCADE`` on ``term_id``), while the posts
themselves survive. This locks that contract as a regression guard for the
fe-admin bulk-delete feature.

Engineering requirements (binding, restated): TDD-first (this RED-first guard
asserts the cascade contract); DevOps-first (clean local + CI from cold start,
real PG via the ``db`` fixture); SOLID/DI/DRY (exercises the existing
``TermService.bulk_delete`` — no new behaviour); Liskov (cascade is the
contract a term delete implies); clean code; no overengineering. Quality
guard: ``bin/pre-commit-check.sh --plugin cms --full``.
"""
import uuid

import pytest

from plugins.cms.src.models.cms_post_term import CmsPostTerm
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
    term_type_registry.register_term_type(
        TermType(key="tag", label="Tag", hierarchical=False)
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


def _term_service(db):
    return TermService(TermRepository(db.session))


def _links_for_term(db, term_id):
    return db.session.query(CmsPostTerm).filter(CmsPostTerm.term_id == term_id).all()


class TestTermBulkDeleteCascade:
    def test_bulk_delete_single_term_clears_junction_keeps_post(self, db):
        post_service = _post_service(db)
        term_service = _term_service(db)

        term = term_service.create_term(
            {"term_type": "tag", "name": "T", "slug": f"t-{uuid.uuid4().hex[:8]}"}
        )
        post = post_service.create_post(
            {"type": "post", "title": "P", "slug": f"p-{uuid.uuid4().hex[:8]}"}
        )
        post_service.assign_terms(post["id"], [term["id"]])

        assert len(_links_for_term(db, term["id"])) == 1

        result = term_service.bulk_delete([term["id"]])

        assert result == {"deleted": 1}
        # (a) the term is gone
        assert TermRepository(db.session).find_by_id(term["id"]) is None
        # (b) the junction row cascaded away
        assert _links_for_term(db, term["id"]) == []
        # (c) the post survives
        assert PostRepository(db.session).find_by_id(post["id"]) is not None

    def test_bulk_delete_multiple_terms_clears_all_junctions_keeps_post(self, db):
        post_service = _post_service(db)
        term_service = _term_service(db)

        category = term_service.create_term(
            {
                "term_type": "category",
                "name": "C",
                "slug": f"c-{uuid.uuid4().hex[:8]}",
            }
        )
        tag = term_service.create_term(
            {"term_type": "tag", "name": "G", "slug": f"g-{uuid.uuid4().hex[:8]}"}
        )
        post = post_service.create_post(
            {"type": "post", "title": "P", "slug": f"p-{uuid.uuid4().hex[:8]}"}
        )
        post_service.assign_terms(post["id"], [category["id"], tag["id"]])

        assert len(_links_for_term(db, category["id"])) == 1
        assert len(_links_for_term(db, tag["id"])) == 1

        result = term_service.bulk_delete([category["id"], tag["id"]])

        assert result == {"deleted": 2}
        assert TermRepository(db.session).find_by_id(category["id"]) is None
        assert TermRepository(db.session).find_by_id(tag["id"]) is None
        assert _links_for_term(db, category["id"]) == []
        assert _links_for_term(db, tag["id"]) == []
        assert PostRepository(db.session).find_by_id(post["id"]) is not None
