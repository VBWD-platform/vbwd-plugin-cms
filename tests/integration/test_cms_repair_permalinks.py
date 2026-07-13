"""Integration (real PG): ``PostService.repair_permalinks`` backs the S-repair
``flask cms repair-permalinks`` command.

A recursion bug fed a post's full stored permalink back into the ``%slug%`` token
on update, so slugs saved before the fix accumulated repeated prefixes
(``blog/news/blog/news/<tail>``). The forward fix stops NEW accumulation; this
command repairs the rows already corrupted in the DB.

Proven here (all through PostService/repositories — no raw SQL, so the suite
runs cold local AND in CI):

* a corrupted accumulated slug collapses to the single-prefix form a fresh save
  would compute, ``slug_base`` becomes the bare tail, and an old→new 301 is
  emitted (the SAME ``_emit_slug_redirect`` the rename path uses);
* idempotency — a second ``apply`` changes nothing;
* dry-run (``apply=False``) writes NOTHING but reports the row as would-change;
* an already-correct post is left untouched and counted already-correct;
* a collision — two posts collapsing to the same slug — repairs one and reports
  the other skipped, never raising the ``(type, slug)`` unique constraint.

Engineering requirements (binding, restated): TDD-first; DevOps-first (schema via
Alembic, data via services); SOLID/DI/DRY (repair reuses the ONE renderer via
``_compute_full_slug`` and the ONE redirect emitter); Liskov (engine-off ⇒ no-op,
preserving today's behaviour); clean code; no overengineering. Quality guard:
``bin/pre-commit-check.sh --plugin cms --full``.
"""
import uuid

import pytest

from plugins.cms.src.models.cms_post import POST_STATUS_PUBLISHED
from plugins.cms.src.models.cms_term import CmsTerm
from plugins.cms.src.repositories.post_repository import PostRepository
from plugins.cms.src.repositories.term_repository import TermRepository
from plugins.cms.src.repositories.post_term_repository import PostTermRepository
from plugins.cms.src.repositories.routing_rule_repository import (
    CmsRoutingRuleRepository,
)
from plugins.cms.src.services import post_type_registry
from plugins.cms.src.services.post_type_registry import PostType
from plugins.cms.src.services.post_service import PostService


STRUCTURED_CONFIG = {
    "posts_permalink_mode": "structured",
    "posts_root": "blog",
    "posts_permalink_include_year": False,
    "posts_permalink_uncategorized_slug": "uncategorized",
    "public_base_url": "https://example.test",
}


@pytest.fixture(autouse=True)
def _post_types():
    post_type_registry.clear_post_types()
    post_type_registry.register_post_type(
        PostType(key="page", label="Page", routable=True, hierarchical=True)
    )
    post_type_registry.register_post_type(
        PostType(key="post", label="Post", routable=True, hierarchical=False)
    )
    yield
    post_type_registry.clear_post_types()


def _service(db, config=None):
    return PostService(
        repo=PostRepository(db.session),
        term_repo=TermRepository(db.session),
        post_term_repo=PostTermRepository(db.session),
        routing_rule_repo=CmsRoutingRuleRepository(db.session),
        permalink_config=dict(config or STRUCTURED_CONFIG),
    )


def _category(db, suffix):
    term_repo = TermRepository(db.session)
    term = CmsTerm()
    term.term_type = "category"
    term.slug = f"news-{suffix}"
    term.name = "News"
    term_repo.save(term)
    return term


def _make_post(service, db, suffix, slug_base, category):
    """Create a structured post + persist its term junction so a later repair
    (which reads the junction, not the create payload) resolves the same
    category the engine used on create."""
    created = service.create_post(
        {
            "type": "post",
            "title": f"Understanding SaaS {suffix}",
            "slug": slug_base,
            "content_html": "<p>Body</p>",
            "status": POST_STATUS_PUBLISHED,
            "term_ids": [str(category.id)],
            "primary_term_id": str(category.id),
        }
    )
    service.assign_terms(created["id"], [str(category.id)])
    return PostRepository(db.session).find_by_id(created["id"])


def _corrupt(db, post, doubled_slug, corrupted_base):
    post.slug = doubled_slug
    post.slug_base = corrupted_base
    PostRepository(db.session).save(post)


def _redirect_rules_for(db, old_slug):
    return [
        rule
        for rule in CmsRoutingRuleRepository(db.session).find_all()
        if rule.match_value == f"/{old_slug}"
    ]


def test_apply_collapses_slug_and_emits_redirect(client, db):
    suffix = uuid.uuid4().hex[:8]
    category = _category(db, suffix)
    service = _service(db)
    post = _make_post(service, db, suffix, f"understanding-saas-{suffix}", category)

    correct = f"blog/news-{suffix}/understanding-saas-{suffix}"
    assert post.slug == correct  # sanity: a fresh save is single-prefix

    doubled = f"blog/news-{suffix}/blog/news-{suffix}/understanding-saas-{suffix}"
    _corrupt(db, post, doubled, correct)  # slug_base corrupted to the full path

    result = service.repair_permalinks(post_type="post", apply=True)

    reloaded = PostRepository(db.session).find_by_id(str(post.id))
    assert reloaded.slug == correct
    assert reloaded.slug_base == f"understanding-saas-{suffix}"
    assert len(result["changes"]) == 1
    assert result["already_correct"] == 0

    rules = _redirect_rules_for(db, doubled)
    assert len(rules) == 1
    assert rules[0].target_slug == f"/{correct}"
    assert rules[0].redirect_code == 301


def test_apply_is_idempotent(client, db):
    suffix = uuid.uuid4().hex[:8]
    category = _category(db, suffix)
    service = _service(db)
    post = _make_post(service, db, suffix, f"understanding-saas-{suffix}", category)
    correct = post.slug
    doubled = f"blog/news-{suffix}/blog/news-{suffix}/understanding-saas-{suffix}"
    _corrupt(db, post, doubled, correct)

    first = service.repair_permalinks(post_type="post", apply=True)
    assert len(first["changes"]) == 1

    second = service.repair_permalinks(post_type="post", apply=True)
    assert len(second["changes"]) == 0
    assert second["already_correct"] == 1
    assert len(_redirect_rules_for(db, doubled)) == 1


def test_dry_run_writes_nothing_but_reports(client, db):
    suffix = uuid.uuid4().hex[:8]
    category = _category(db, suffix)
    service = _service(db)
    post = _make_post(service, db, suffix, f"understanding-saas-{suffix}", category)
    correct = post.slug
    doubled = f"blog/news-{suffix}/blog/news-{suffix}/understanding-saas-{suffix}"
    _corrupt(db, post, doubled, correct)

    result = service.repair_permalinks(post_type="post", apply=False)

    assert result["applied"] is False
    assert len(result["changes"]) == 1
    assert result["changes"][0]["old_slug"] == doubled
    assert result["changes"][0]["new_slug"] == correct

    reloaded = PostRepository(db.session).find_by_id(str(post.id))
    assert reloaded.slug == doubled  # untouched
    assert reloaded.slug_base == correct
    assert _redirect_rules_for(db, doubled) == []


def test_already_correct_post_untouched(client, db):
    suffix = uuid.uuid4().hex[:8]
    category = _category(db, suffix)
    service = _service(db)
    post = _make_post(service, db, suffix, f"understanding-saas-{suffix}", category)
    correct = post.slug

    result = service.repair_permalinks(post_type="post", apply=True)

    assert len(result["changes"]) == 0
    assert result["already_correct"] == result["scanned"] >= 1
    reloaded = PostRepository(db.session).find_by_id(str(post.id))
    assert reloaded.slug == correct


def test_collision_repairs_one_and_skips_other(client, db):
    suffix = uuid.uuid4().hex[:8]
    category = _category(db, suffix)
    service = _service(db)
    tail = f"understanding-saas-{suffix}"
    correct = f"blog/news-{suffix}/{tail}"

    first = _make_post(service, db, suffix, tail, category)
    second = _make_post(service, db, f"{suffix}b", tail, category)
    # ``second`` was uniquified on create; both collapse to ``correct``.
    assert second.slug != correct

    doubled = f"blog/news-{suffix}/blog/news-{suffix}/{tail}"
    _corrupt(db, first, doubled, correct)

    result = service.repair_permalinks(post_type="post", apply=True)

    assert result["scanned"] >= 2
    assert len(result["changes"]) == 1
    assert len(result["collisions"]) == 1
    # No unique-constraint explosion: the two rows never share a slug.
    repo = PostRepository(db.session)
    assert repo.find_by_id(str(first.id)).slug != repo.find_by_id(str(second.id)).slug
