"""Repo-level: PostRepository.find_by_slug_prefix LIKE-wildcard escaping.

The prefix-archive query matches ``slug LIKE '<prefix>/%'``. A prefix that
literally contains a SQL LIKE wildcard (``_`` = any one char, ``%`` = any run)
must be escaped, or a slug segment carrying those characters would silently
widen the match and pull in unrelated posts. These tests prove the escape by
seeding a decoy whose slug would ONLY match if the wildcard were live.

Uses the real ``db`` session (LIKE-escape semantics are a database behaviour, so
a fake would not prove anything) but is a narrow single-method repo test — no
route, no service.

Engineering requirements (binding, restated): TDD-first (this RED set);
DevOps-first (real PostgreSQL, cold local + CI); SOLID/DI/DRY (one query, one
escape rule); Liskov; clean code; no overengineering. Quality guard:
``bin/pre-commit-check.sh --plugin cms --full``.
"""
import uuid

from plugins.cms.src.models.cms_post import CmsPost
from plugins.cms.src.repositories.post_repository import PostRepository


def _make_published(db, slug):
    post = CmsPost()
    post.type = "post"
    post.slug = slug
    post.title = slug
    post.content_json = {}
    post.status = "published"
    db.session.add(post)
    db.session.commit()
    return post


def test_underscore_in_prefix_is_escaped_not_a_wildcard(db):
    run = uuid.uuid4().hex[:8]
    literal = _make_published(db, f"{run}/a_b/x")
    decoy = _make_published(db, f"{run}/aXb/y")

    result = PostRepository(db.session).find_by_slug_prefix(f"{run}/a_b")

    slugs = {item.slug for item in result["items"]}
    assert literal.slug in slugs
    # Without escaping, LIKE '<run>/a_b/%' would match '<run>/aXb/y' too.
    assert decoy.slug not in slugs
    assert result["total"] == 1


def test_percent_in_prefix_is_escaped_not_a_wildcard(db):
    run = uuid.uuid4().hex[:8]
    literal = _make_published(db, f"{run}/a%b/z")
    decoy = _make_published(db, f"{run}/aZZZb/w")

    result = PostRepository(db.session).find_by_slug_prefix(f"{run}/a%b")

    slugs = {item.slug for item in result["items"]}
    assert literal.slug in slugs
    # Without escaping, LIKE '<run>/a%b/%' would match '<run>/aZZZb/w' too.
    assert decoy.slug not in slugs
    assert result["total"] == 1


def test_prefix_normalizes_leading_and_trailing_slashes(db):
    run = uuid.uuid4().hex[:8]
    post = _make_published(db, f"{run}/deep/leaf")

    result = PostRepository(db.session).find_by_slug_prefix(f"/{run}/deep/")

    assert result["total"] == 1
    assert result["items"][0].slug == post.slug
