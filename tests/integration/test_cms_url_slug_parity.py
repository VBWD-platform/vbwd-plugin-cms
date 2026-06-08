"""URL & slug parity gate — the prod-safety regression test (S47.0).

"Nothing is lost on prod": after the cms_page -> cms_post backfill, the set of
published page slugs, their canonical URLs, and their content_html must be
identical to the pre-migration snapshot. Zero pages dropped, zero silent slug
changes; a (type, slug) collision under the new namespace resolves via a 301
routing record (the slug-change seam) instead of a drop/404.

The serving-side no-404 / prerendered-file parity is owned by 47.1/47.2; here
we assert the DATA/slug/canonical parity that those layers rely on.

Seeds the current page set from a REAL ``docs/imports/pages/*.json`` fixture
(loaded through the legacy import path) plus a small synthetic set including an
edge case (special characters / a would-be slug collision).
"""
import hashlib
import io
import json
import os
import uuid
import zipfile

from plugins.cms.src.repositories.cms_page_repository import CmsPageRepository
from plugins.cms.src.repositories.cms_category_repository import CmsCategoryRepository
from plugins.cms.src.repositories.post_repository import PostRepository
from plugins.cms.src.repositories.term_repository import TermRepository
from plugins.cms.src.repositories.routing_rule_repository import (
    CmsRoutingRuleRepository,
)
from plugins.cms.src.services.cms_backfill_service import CmsBackfillService
from plugins.cms.src.services.cms_import_export_service import CmsImportExportService
from vbwd.interfaces.file_storage import InMemoryFileStorage

_IMPORTS_PAGES_DIR = os.path.join(
    os.path.dirname(__file__),
    "..",
    "..",
    "docs",
    "imports",
    "pages",
)


def _load_real_fixture_pages():
    """Load the real docs/imports/pages/*.json seed pages as legacy records."""
    records = []
    for name in sorted(os.listdir(_IMPORTS_PAGES_DIR)):
        if not name.endswith(".json"):
            continue
        with open(os.path.join(_IMPORTS_PAGES_DIR, name)) as handle:
            record = json.load(handle)
        # Strip layout/style/category cross-references the legacy page importer
        # would try to resolve — parity is about slug/canonical/content, not FK.
        record.pop("layout_slug", None)
        record.pop("style_slug", None)
        record.pop("category_slug", None)
        record.pop("page_widget_assignments", None)
        records.append(record)
    return records


def _legacy_zip(pages):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(
            "manifest.json",
            json.dumps({"version": "1.0", "sections": ["pages"]}),
        )
        zf.writestr("pages.json", json.dumps(pages))
    buf.seek(0)
    return buf.read()


def _legacy_import_service(db):
    page_repo = CmsPageRepository(db.session)
    cat_repo = CmsCategoryRepository(db.session)
    from unittest.mock import MagicMock

    stub = MagicMock()
    stub.find_all.return_value = {"items": []}
    stub.find_by_slug.return_value = None
    return CmsImportExportService(
        cat_repo,
        stub,  # style
        stub,  # widget
        stub,  # layout
        page_repo,
        stub,  # routing
        stub,  # image
        stub,  # lw
        InMemoryFileStorage(),
    )


def _backfill_service(db):
    return CmsBackfillService(
        page_repo=CmsPageRepository(db.session),
        category_repo=CmsCategoryRepository(db.session),
        post_repo=PostRepository(db.session),
        term_repo=TermRepository(db.session),
        routing_repo=CmsRoutingRuleRepository(db.session),
    )


def _content_hash(value):
    return hashlib.sha256((value or "").encode("utf-8")).hexdigest()


def _snapshot_published_pages(db):
    """{slug: {canonical_url, content_hash}} for every published cms_page."""
    snapshot = {}
    result = CmsPageRepository(db.session).find_all(
        per_page=100000, filters={"is_published": True}
    )
    for page in result["items"]:
        snapshot[page.slug] = {
            "canonical_url": page.canonical_url,
            "content_hash": _content_hash(page.content_html),
            "public_path": f"/{page.slug}",
        }
    return snapshot


def _snapshot_published_posts(db):
    """{slug: {canonical_url, content_hash}} for every published cms_post(page)."""
    snapshot = {}
    result = PostRepository(db.session).find_paginated(
        post_type="page", status="published", per_page=100000
    )
    for post in result["items"]:
        snapshot[post.slug] = {
            "canonical_url": post.canonical_url,
            "content_hash": _content_hash(post.content_html),
            "public_path": f"/{post.slug}",
        }
    return snapshot


class TestUrlSlugParity:
    def test_real_fixture_set_has_zero_slug_changes(self, db):
        # Seed the live page set from the real docs/imports fixtures through
        # the legacy import path, plus a synthetic special-char edge case.
        marker = uuid.uuid4().hex[:8]
        legacy_pages = _load_real_fixture_pages()
        # Namespace fixture slugs to keep the test DB shared-state-safe while
        # still exercising real content/canonical/slug values.
        for record in legacy_pages:
            record["slug"] = f"{record['slug']}-{marker}"
            record.setdefault("is_published", True)
        legacy_pages.append(
            {
                "slug": f"café-résumé-{marker}",
                "name": "Edge — accents & special chars",
                "language": "en",
                "content_json": {"type": "doc", "content": []},
                "content_html": "<h1>Café Résumé — © 2026</h1>",
                "is_published": True,
                "canonical_url": f"https://example.test/cafe-resume-{marker}",
                "robots": "index,follow",
            }
        )
        _legacy_import_service(db).import_zip(_legacy_zip(legacy_pages), "add")

        before = _snapshot_published_pages(db)
        before = {slug: data for slug, data in before.items() if slug.endswith(marker)}
        assert before, "fixture seeding produced no published pages"

        _backfill_service(db).backfill()

        after_all = _snapshot_published_posts(db)
        after = {
            slug: data for slug, data in after_all.items() if slug.endswith(marker)
        }

        # 1. Zero dropped pages + slug set identical (count + set equality).
        missing = set(before) - set(after)
        added = set(after) - set(before)
        assert not missing, f"DROPPED pages after backfill: {sorted(missing)}"
        assert not added, f"UNEXPECTED new slugs after backfill: {sorted(added)}"
        assert len(before) == len(after)

        # 2. canonical_url + content_html identical per page — fail loud listing
        #    the exact differing slugs/URLs.
        canonical_diffs = [
            slug
            for slug in before
            if before[slug]["canonical_url"] != after[slug]["canonical_url"]
        ]
        content_diffs = [
            slug
            for slug in before
            if before[slug]["content_hash"] != after[slug]["content_hash"]
        ]
        assert not canonical_diffs, "canonical_url diverged for: " + ", ".join(
            f"{slug} ({before[slug]['canonical_url']} -> "
            f"{after[slug]['canonical_url']})"
            for slug in canonical_diffs
        )
        assert not content_diffs, f"content_html diverged for: {content_diffs}"


class TestSlugCollisionResolvesVia301:
    def test_collision_creates_redirect_record_not_a_drop(self, db):
        # A cms_post(type=page) already occupies the target slug; a cms_page
        # with the SAME slug must NOT be dropped on backfill — it gets a
        # collision-resolved slug AND a 301 record from the old path.
        marker = uuid.uuid4().hex[:8]
        taken_slug = f"clash-{marker}"

        # Pre-existing unified page at the slug.
        from plugins.cms.src.models.cms_post import CmsPost

        occupant = CmsPost()
        occupant.type = "page"
        occupant.slug = taken_slug
        occupant.title = "Occupant"
        occupant.content_json = {}
        occupant.status = "published"
        db.session.add(occupant)
        db.session.commit()

        # Legacy cms_page with the same slug (the collision source).
        _legacy_import_service(db).import_zip(
            _legacy_zip(
                [
                    {
                        "slug": taken_slug,
                        "name": "Legacy Clash",
                        "content_html": "<h1>Legacy</h1>",
                        "is_published": True,
                        "canonical_url": f"https://example.test/{taken_slug}",
                    }
                ]
            ),
            "add",
        )

        _backfill_service(db).backfill()

        # The legacy page is NOT lost: a second page post exists under a
        # collision-resolved slug.
        posts = PostRepository(db.session).find_paginated(
            post_type="page", per_page=100000
        )["items"]
        clash_posts = [p for p in posts if p.slug.startswith(taken_slug)]
        assert len(clash_posts) >= 2, "collision dropped the legacy page"

        # A 301 redirect record bridges the old path to the resolved slug.
        rules = CmsRoutingRuleRepository(db.session).find_all()
        redirect = [
            r
            for r in rules
            if r.redirect_code == 301 and taken_slug in (r.match_value or "")
        ]
        assert redirect, "no 301 record created for the colliding slug"
