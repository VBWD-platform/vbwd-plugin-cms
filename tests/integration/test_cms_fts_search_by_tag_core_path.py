"""S77 D7 follow-up — FTS search filtered by tag reads the core tag path.

After folding CMS tags into the core ``vbwd_entity_tag`` table, a full-text
search narrowed by ``term_type=tag`` must resolve the post set via the core
reverse index (entity_type ``cms_post``), NOT ``cms_post_term``/
``cms_term('tag')`` (which no longer holds tags). Category filtering
(``term_type=category``) is unchanged — still the ``cms_term``/``cms_post_term``
join. Mirrors the D7 pattern in ``PostRepository.find_by_tag_slug``.

Engineering requirements (binding, restated): TDD-first; DevOps-first (real PG
via the ``db`` fixture, clean cold start); SOLID/DI/DRY (tags via the core port;
one home for the reverse-index lookup); Liskov; clean code; no overengineering.
Quality guard: ``bin/pre-commit-check.sh --plugin cms --full``.
"""
import uuid

import pytest

from plugins.cms.src.models.cms_post import POST_STATUS_PUBLISHED
from plugins.cms.src.repositories.post_repository import PostRepository
from plugins.cms.src.repositories.post_term_repository import PostTermRepository
from plugins.cms.src.repositories.search_repository import SearchRepository
from plugins.cms.src.repositories.term_repository import TermRepository
from plugins.cms.src.services.post_service import PostService
from plugins.cms.src.services.search_service import SearchService
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


def _search_service(db):
    return SearchService(repo=SearchRepository(db.session))


def _slugs(result):
    return [item["slug"] for item in result["items"]]


def test_tag_filter_uses_core_entity_tag(app, db):
    """A text match carrying a core tag is returned; an untagged text match is not."""
    marker = uuid.uuid4().hex[:8]
    tag_slug = f"featured-{marker}"
    post_service = _post_service(db)

    tagged = post_service.create_post(
        {
            "type": "post",
            "title": f"Hospitality industry {marker}",
            "slug": f"hosp-tagged-{marker}",
            "status": POST_STATUS_PUBLISHED,
        }
    )
    untagged = post_service.create_post(
        {
            "type": "post",
            "title": f"Hospitality staffing {marker}",
            "slug": f"hosp-untagged-{marker}",
            "status": POST_STATUS_PUBLISHED,
        }
    )

    with app.app_context():
        app.container.tags_and_custom_fields().set_tags(
            "cms_post", tagged["id"], [tag_slug]
        )

    result = _search_service(db).search(
        "hospitality",
        term_filter=("tag", tag_slug),
        page=1,
        per_page=50,
    )

    slugs = _slugs(result)
    assert tagged["slug"] in slugs
    assert untagged["slug"] not in slugs
    assert result["total"] == 1


def test_category_filter_still_uses_cms_term(app, db):
    """Regression: category narrowing stays on the cms_term/cms_post_term join."""
    marker = uuid.uuid4().hex[:8]
    post_service = _post_service(db)
    term_service = TermService(TermRepository(db.session))

    in_category = post_service.create_post(
        {
            "type": "post",
            "title": f"Hospitality industry {marker}",
            "slug": f"hosp-cat-{marker}",
            "status": POST_STATUS_PUBLISHED,
        }
    )
    out_category = post_service.create_post(
        {
            "type": "post",
            "title": f"Hospitality staffing {marker}",
            "slug": f"hosp-nocat-{marker}",
            "status": POST_STATUS_PUBLISHED,
        }
    )
    news = term_service.create_term(
        {"term_type": "category", "name": "News", "slug": f"news-{marker}"}
    )
    post_service.assign_terms(in_category["id"], [news["id"]])

    result = _search_service(db).search(
        "hospitality",
        term_filter=("category", f"news-{marker}"),
        page=1,
        per_page=50,
    )

    slugs = _slugs(result)
    assert in_category["slug"] in slugs
    assert out_category["slug"] not in slugs
    assert result["total"] == 1
