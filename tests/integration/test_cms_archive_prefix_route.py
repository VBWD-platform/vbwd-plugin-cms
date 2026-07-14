"""Integration: GET /api/v1/cms/archive/<path:prefix> (WordPress-style prefix archives).

Post permalinks store the FULL path in ``cms_post.slug`` (e.g.
``blog/2026/news/vbwd-v26-7-0-released``). Every PREFIX of that path must resolve
to an archive listing of the published posts beneath it, via one config-agnostic
rule: the archive at prefix ``P`` = all PUBLISHED posts whose ``slug`` starts with
``P/`` (the trailing slash enforces a SEGMENT boundary, so ``blog/2026`` never
matches ``blog/20260-x`` or ``blog/2026/newsroom`` bleed). No year parsing, no
category joins — a pure slug-prefix match.

Engineering requirements (binding, restated): TDD-first (this RED set);
DevOps-first (real PostgreSQL via the ``db`` fixture, cold local + CI); SOLID/DI/
DRY (one repo query reusing the shared ordering helper, one service envelope
mirroring ``list_posts``, one route mirroring ``public_list_posts``); Liskov (an
unknown prefix is a clean 404, draft/non-published excluded uniformly); clean
code; no overengineering. Quality guard: ``bin/pre-commit-check.sh --plugin cms
--full``.
"""
import uuid
from datetime import datetime, timedelta, timezone

from plugins.cms.src.models.cms_post import CmsPost


def _make_post(db, slug, status="published", published_at=None):
    post = CmsPost()
    post.type = "post"
    post.slug = slug
    post.title = slug.rsplit("/", 1)[-1]
    post.content_json = {}
    post.status = status
    post.published_at = published_at
    db.session.add(post)
    db.session.commit()
    return post


def _seed_archive_tree(db, prefix):
    """Seed the canonical archive tree under a unique run prefix.

    ``a`` and ``b`` sit under ``<prefix>/2026/news`` (b published later so it
    sorts first newest-first); ``x`` under ``<prefix>/2025``; ``draft`` under
    ``<prefix>/2026/news`` but not published. Returns the run prefix segments.
    """
    now = datetime.now(timezone.utc)
    _make_post(db, f"{prefix}/2026/news/a", published_at=now - timedelta(days=2))
    _make_post(db, f"{prefix}/2026/news/b", published_at=now - timedelta(days=1))
    _make_post(db, f"{prefix}/2025/x", published_at=now - timedelta(days=3))
    _make_post(db, f"{prefix}/2026/news/draft", status="draft")


def test_archive_at_deepest_prefix_lists_only_its_posts_newest_first(app, db, client):
    prefix = f"blog-{uuid.uuid4().hex[:8]}"
    _seed_archive_tree(db, prefix)

    response = client.get(f"/api/v1/cms/archive/{prefix}/2026/news")
    body = response.get_json()

    assert response.status_code == 200
    assert body["prefix"] == f"{prefix}/2026/news"
    assert body["total"] == 2
    # Newest-first: b (published yesterday) before a (two days ago).
    slugs = [item["slug"] for item in body["items"]]
    assert slugs == [f"{prefix}/2026/news/b", f"{prefix}/2026/news/a"]


def test_archive_title_is_last_segment_titlecased(app, db, client):
    prefix = f"blog-{uuid.uuid4().hex[:8]}"
    _seed_archive_tree(db, prefix)

    news = client.get(f"/api/v1/cms/archive/{prefix}/2026/news").get_json()
    year = client.get(f"/api/v1/cms/archive/{prefix}/2026").get_json()

    assert news["title"] == "News"
    assert year["title"] == "2026"


def test_archive_at_year_prefix_excludes_other_years(app, db, client):
    prefix = f"blog-{uuid.uuid4().hex[:8]}"
    _seed_archive_tree(db, prefix)

    response = client.get(f"/api/v1/cms/archive/{prefix}/2026")
    body = response.get_json()

    assert response.status_code == 200
    # a + b live under .../2026; .../2025/x is excluded.
    assert body["total"] == 2
    slugs = {item["slug"] for item in body["items"]}
    assert slugs == {f"{prefix}/2026/news/a", f"{prefix}/2026/news/b"}


def test_archive_at_root_prefix_lists_all_published_descendants(app, db, client):
    prefix = f"blog-{uuid.uuid4().hex[:8]}"
    _seed_archive_tree(db, prefix)

    response = client.get(f"/api/v1/cms/archive/{prefix}")
    body = response.get_json()

    assert response.status_code == 200
    # a, b, x are published under the root; the draft is excluded.
    assert body["total"] == 3


def test_archive_segment_boundary_excludes_sibling_prefix(app, db, client):
    prefix = f"blog-{uuid.uuid4().hex[:8]}"
    _seed_archive_tree(db, prefix)
    # A decoy whose parent segment merely STARTS with "news" must not leak into
    # the "news" archive — the trailing-slash pattern enforces the boundary.
    _make_post(
        db,
        f"{prefix}/2026/newsroom/z",
        published_at=datetime.now(timezone.utc),
    )

    response = client.get(f"/api/v1/cms/archive/{prefix}/2026/news")
    body = response.get_json()

    assert response.status_code == 200
    assert body["total"] == 2
    slugs = {item["slug"] for item in body["items"]}
    assert f"{prefix}/2026/newsroom/z" not in slugs


def test_unknown_prefix_returns_404(app, db, client):
    response = client.get("/api/v1/cms/archive/does/not/exist")

    assert response.status_code == 404
    assert "error" in response.get_json()


def test_archive_pagination_walks_pages_newest_first(app, db, client):
    prefix = f"blog-{uuid.uuid4().hex[:8]}"
    _seed_archive_tree(db, prefix)

    first = client.get(
        f"/api/v1/cms/archive/{prefix}/2026/news?per_page=1&page=1"
    ).get_json()
    second = client.get(
        f"/api/v1/cms/archive/{prefix}/2026/news?per_page=1&page=2"
    ).get_json()

    assert first["total"] == 2
    assert first["pages"] == 2
    assert first["per_page"] == 1
    assert [item["slug"] for item in first["items"]] == [f"{prefix}/2026/news/b"]
    assert [item["slug"] for item in second["items"]] == [f"{prefix}/2026/news/a"]
