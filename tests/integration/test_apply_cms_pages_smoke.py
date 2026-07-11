"""Smoke test: the three-page CMS applier runs the way deploy calls it.

Deploy invokes the script as:
    docker compose exec -T -e PYTHONPATH=/app api \
        python /app/plugins/cms/src/bin/apply_cms_pages.py
which boils down to ``with create_app().app_context(): main()``. This test
seeds the layout / parent page / category term the docs page references (through
the repositories, no raw SQL), drives the applier's DB entrypoint, and asserts
all three pages are created, resolve by slug with the expected layout/parent,
and that a second run is idempotent (counts move to ``updated``, no duplicates).

Engineering requirements (binding, restated): TDD-first (written before the
applier); DevOps-first (clean local + CI from cold start; DB via the rolled-back
``db`` fixture); SOLID/DI/DRY (imports run through the single
PostImportExportService the routes use); Liskov (upsert-by-(type,slug) is
behaviour-preserving on re-run); clean code; no overengineering. Quality guard:
``bin/pre-commit-check.sh --plugin cms --full``.
"""
from plugins.cms.src.bin import apply_cms_pages
from plugins.cms.src.models.cms_layout import CmsLayout
from plugins.cms.src.models.cms_post import CmsPost
from plugins.cms.src.repositories.cms_layout_repository import CmsLayoutRepository
from plugins.cms.src.repositories.post_repository import PostRepository
from plugins.cms.src.repositories.term_repository import TermRepository
from plugins.cms.src.models.cms_term import CmsTerm


_EXPECTED_SLUGS = (
    "pricing-native",
    "pricing-embedded",
    "docs-core-subscription/tarif-plans",
)


def _seed_referenced_dependencies(session):
    """Seed the layout, parent page and category the docs page resolves by slug.

    The other two pages reference their own layouts (``native-pricing-page`` /
    the embedded page's layout); those need not exist for the import to create
    the page (unknown layout_slug resolves to None), so this seeds only what the
    resolution assertions below require: the ``content-page`` layout, the
    ``docs-core-subscription`` parent page, and the ``vbwd-core-subscription``
    category term.
    """
    CmsLayoutRepository(session).save(
        CmsLayout(name="Content Page", slug="content-page", areas=[])
    )
    parent = CmsPost()
    parent.type = "page"
    parent.slug = "docs-core-subscription"
    parent.title = "Subscription"
    parent.status = "published"
    PostRepository(session).save(parent)
    TermRepository(session).save(
        CmsTerm(
            term_type="category", name="Subscription", slug="vbwd-core-subscription"
        )
    )


def test_applier_creates_all_three_pages_and_is_idempotent(db):
    _seed_referenced_dependencies(db.session)
    post_repo = PostRepository(db.session)

    first = apply_cms_pages.apply_cms_pages(db.session)

    total_created = sum(result["created"] for result in first.values())
    assert total_created == 3
    for slug in _EXPECTED_SLUGS:
        assert post_repo.find_by_type_and_slug("page", slug) is not None

    # Second run: no new posts, everything reports as updated.
    posts_after_first = db.session.query(CmsPost).count()
    second = apply_cms_pages.apply_cms_pages(db.session)

    assert db.session.query(CmsPost).count() == posts_after_first
    assert sum(result["created"] for result in second.values()) == 0
    assert sum(result["updated"] for result in second.values()) == 3


def test_docs_page_resolves_with_expected_layout_and_parent(db):
    _seed_referenced_dependencies(db.session)

    apply_cms_pages.apply_cms_pages(db.session)

    post_repo = PostRepository(db.session)
    layout_repo = CmsLayoutRepository(db.session)
    docs_page = post_repo.find_by_type_and_slug(
        "page", "docs-core-subscription/tarif-plans"
    )
    assert docs_page is not None
    assert docs_page.layout_id == layout_repo.find_by_slug("content-page").id
    parent = post_repo.find_by_type_and_slug("page", "docs-core-subscription")
    assert docs_page.parent_id == parent.id


def test_main_entrypoint_imports_the_curated_pages(db):
    _seed_referenced_dependencies(db.session)

    # Drive the exact entrypoint deploy runs (the __main__ block calls main()
    # under an app context; the db fixture already supplies one).
    apply_cms_pages.main()

    post_repo = PostRepository(db.session)
    for slug in _EXPECTED_SLUGS:
        assert post_repo.find_by_type_and_slug("page", slug) is not None
