"""CmsBackfillService — folds live cms_page / cms_category rows into the
unified cms_post / cms_term tables (S47.0 increment 2).

This is a COPY, not a move: the legacy ``cms_page`` / ``cms_category`` tables
and their data stay intact for one release so any un-migrated caller keeps
working (see ``cms_page_read_shim``). The backfill is idempotent — a row whose
``(type, slug)`` (or ``(term_type, slug)``) already exists in the target is
skipped, so a second pass creates nothing new and is safe to re-run on every
deploy. No raw SQL: every read/write goes through repositories.

Column mapping (cms_page -> cms_post, type=page):
  - SEO columns copied 1:1 (meta_*, og_*, canonical_url, robots, schema_json);
    ``seo_excluded`` defaults False (cms_page has no such column).
  - content_html / content_json / slug / language copied verbatim.
  - cms_page.name -> cms_post.title; cms_page is_published -> status
    (``published`` / ``draft``).
  - parent_id is left NULL — page nesting is unknown at migrate time.

The bulk copy fires at most ONE ``content.changed`` signal (not one per row)
to avoid a prerender storm in the 47.1 writer.
"""
import hashlib
from typing import Any, Dict, Optional

from vbwd.events.dispatcher import Event

from plugins.cms.src.models.cms_post import (
    CmsPost,
    POST_STATUS_DRAFT,
    POST_STATUS_PUBLISHED,
)
from plugins.cms.src.models.cms_term import CmsTerm


BULK_BACKFILL_EVENT = "content.changed"
PAGE_POST_TYPE = "page"
CATEGORY_TERM_TYPE = "category"
REDIRECT_CODE_PERMANENT = 301
_MAX_SLUG_COLLISION_ATTEMPTS = 10_000


def _content_fingerprint(content_html: Optional[str]) -> str:
    return hashlib.sha256((content_html or "").encode("utf-8")).hexdigest()


class CmsBackfillService:
    """Idempotent service that copies legacy CMS rows into the unified model."""

    def __init__(
        self,
        page_repo,
        category_repo,
        post_repo,
        term_repo,
        event_dispatcher=None,
        routing_repo=None,
    ) -> None:
        self._page_repo = page_repo
        self._category_repo = category_repo
        self._post_repo = post_repo
        self._term_repo = term_repo
        self._event_dispatcher = event_dispatcher
        # Optional: when present, a genuine slug collision is bridged with a
        # 301 record instead of dropping the page (the slug-change seam).
        self._routing_repo = routing_repo

    def backfill(self) -> Dict[str, int]:
        """Run the full backfill. Returns a per-section copied/skipped summary."""
        summary = {
            "pages_copied": 0,
            "pages_skipped": 0,
            "categories_copied": 0,
            "categories_skipped": 0,
        }

        for page in self._all_pages():
            existing = self._post_repo.find_by_type_and_slug(PAGE_POST_TYPE, page.slug)
            if existing is not None:
                if self._is_same_page(existing, page):
                    # Idempotent: this page was already backfilled. Re-apply the
                    # layout/style/theme fields so a re-run picks up a page whose
                    # theme changed (or was themed after the first backfill).
                    self._sync_layout_style(existing, page)
                    summary["pages_skipped"] += 1
                    continue
                # Genuine collision: a DIFFERENT post owns this slug. Never
                # drop the page — copy it under a free slug and bridge the old
                # path with a 301 so no existing link 404s.
                self._backfill_with_collision(page)
                summary["pages_copied"] += 1
                continue
            self._post_repo.save(self._page_to_post(page))
            summary["pages_copied"] += 1

        for category in self._category_repo.find_all():
            if self._term_repo.find_by_type_and_slug(CATEGORY_TERM_TYPE, category.slug):
                summary["categories_skipped"] += 1
                continue
            self._term_repo.save(self._category_to_term(category))
            summary["categories_copied"] += 1

        if summary["pages_copied"] or summary["categories_copied"]:
            self._emit_bulk_signal(summary)
        return summary

    # ── helpers ──────────────────────────────────────────────────────────

    def _all_pages(self):
        return self._page_repo.find_all(per_page=100000)["items"]

    def _is_same_page(self, existing_post, page) -> bool:
        """True when ``existing_post`` is the backfill of ``page`` (re-run).

        Without a provenance column we treat identical content_html as the
        same page — so re-running over the same set is a no-op, while a
        different page competing for the slug is a genuine collision.
        """
        return _content_fingerprint(existing_post.content_html) == _content_fingerprint(
            page.content_html
        )

    def _backfill_with_collision(self, page) -> None:
        free_slug = self._free_page_slug(page.slug)
        post = self._page_to_post(page)
        post.slug = free_slug
        self._post_repo.save(post)
        self._record_301(old_slug=page.slug, new_slug=free_slug)

    def _free_page_slug(self, base_slug: str) -> str:
        for suffix in range(2, _MAX_SLUG_COLLISION_ATTEMPTS):
            candidate = f"{base_slug}-{suffix}"
            if not self._post_repo.find_by_type_and_slug(PAGE_POST_TYPE, candidate):
                return candidate
        raise RuntimeError(f"Could not resolve a free slug for '{base_slug}'")

    def _record_301(self, old_slug: str, new_slug: str) -> None:
        if self._routing_repo is None:
            return
        from plugins.cms.src.models.cms_routing_rule import CmsRoutingRule

        rule = CmsRoutingRule()
        rule.name = f"backfill-301-{old_slug}"
        rule.is_active = True
        rule.priority = 0
        rule.match_type = "path_prefix"
        rule.match_value = f"/{old_slug}"
        rule.target_slug = new_slug
        rule.redirect_code = REDIRECT_CODE_PERMANENT
        rule.is_rewrite = False
        rule.layer = "middleware"
        self._routing_repo.save(rule)

    def _page_to_post(self, page) -> CmsPost:
        post = CmsPost()
        post.type = PAGE_POST_TYPE
        post.slug = page.slug
        post.title = page.name
        post.content_json = page.content_json or {}
        post.content_html = page.content_html
        post.parent_id = None
        post.status = POST_STATUS_PUBLISHED if page.is_published else POST_STATUS_DRAFT
        post.language = page.language or "en"
        post.translation_group_id = getattr(page, "translation_group_id", None)
        post.sort_order = page.sort_order or 0
        post.meta_title = page.meta_title
        post.meta_description = page.meta_description
        post.meta_keywords = page.meta_keywords
        post.og_title = page.og_title
        post.og_description = page.og_description
        post.og_image_url = page.og_image_url
        post.canonical_url = page.canonical_url
        post.robots = page.robots or "index,follow"
        post.schema_json = page.schema_json
        post.seo_excluded = getattr(page, "seo_excluded", False) or False
        self._copy_layout_style(page, post)
        return post

    def _copy_layout_style(self, page, post) -> None:
        """Copy the page's layout/style onto the post.

        cms_post carries the same theming fields as cms_page, so a backfilled
        post looks identical to its source page.
        """
        post.layout_id = getattr(page, "layout_id", None)
        post.style_id = getattr(page, "style_id", None)

    def _sync_layout_style(self, post, page) -> None:
        """Re-apply layout/style on an already-migrated post (idempotent).

        Saves only when one of the fields actually differs, so a steady-state
        re-run writes nothing.
        """
        new_layout = getattr(page, "layout_id", None)
        new_style = getattr(page, "style_id", None)
        if post.layout_id == new_layout and post.style_id == new_style:
            return
        post.layout_id = new_layout
        post.style_id = new_style
        self._post_repo.save(post)

    def _category_to_term(self, category) -> CmsTerm:
        term = CmsTerm()
        term.term_type = CATEGORY_TERM_TYPE
        term.slug = category.slug
        term.name = category.name
        # parent_id maps category -> category later; left NULL here because the
        # parent category may not yet be present as a term during this pass.
        term.parent_id = None
        term.description = getattr(category, "description", None)
        term.sort_order = category.sort_order or 0
        return term

    def _emit_bulk_signal(self, summary: Dict[str, int]) -> None:
        if self._event_dispatcher is None:
            return
        self._event_dispatcher.dispatch(
            Event(name=BULK_BACKFILL_EVENT, data={"reason": "bulk_backfill", **summary})
        )


def resolve_page_by_slug(page_repo, post_repo, slug: str) -> Optional[Dict[str, Any]]:
    """One-release read shim: resolve a page by slug, unified-first.

    During the one-release migration window a caller can ask for a page by
    slug without knowing whether it has been backfilled yet. We prefer the
    unified ``cms_post(type=page)`` row when present and fall back to the
    legacy ``cms_page`` row, so existing reads never break while callers move
    over. Remove once every reader speaks the unified model.
    """
    post = post_repo.find_by_type_and_slug(PAGE_POST_TYPE, slug)
    if post is not None:
        return post.to_dict()
    page = page_repo.find_by_slug(slug)
    if page is not None:
        return page.to_dict()
    return None
