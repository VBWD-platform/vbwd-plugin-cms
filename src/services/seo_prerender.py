"""The Python-template prerender writer (S47.1 §4, D7).

Subscribes to ``content.changed`` and keeps ``${VAR_DIR}/seo/<slug>.html`` in
sync with a post's status:

  - ``published``           → write a public file (indexed unless excluded);
  - ``published`` + excluded → write the file BUT with ``robots: noindex`` (a
                               direct-link visitor still gets the fast page);
  - ``private``/``draft``/``scheduled``/``pending`` → write nothing;
  - ``trash``/unpublish/delete → remove the file.

The file is keyed by the **canonical slug**, never a raw request URL. A
context-dependent cms routing **rewrite** that targets a canonical indexed slug
(cloaking / duplicate content) is **skipped + logged**.

The document is ``<head>`` (meta-builder) + ``<body><div id="app">{content}</div>``
+ an inlined ``__POST__`` JSON payload so the SPA mounts without a re-fetch.
"""
import json
import logging
import os
from typing import Any, Callable, List, Optional

from vbwd.services.filesystem.local import LocalFilesystemManager

from plugins.cms.src.services.seo_asset_stamp import (
    SeoAssetStamper,
    render_asset_block,
)
from plugins.cms.src.services.prerender_minifier import PrerenderMinifier
from plugins.cms.src.services.seo_full_page_renderer import IFullPageRenderer
from plugins.cms.src.services.seo_meta_builder import build_meta
from plugins.cms.src.services.seo_renderable_post import (
    NOINDEX_ROBOTS,
    RenderablePost,
    RenderableSibling,
)
from plugins.cms.src.services.seo_scope import page_is_search_visible
from plugins.cms.src.models.cms_post import POST_STATUS_PUBLISHED

logger = logging.getLogger(__name__)

# The prerendered HTML lives under the ``seo`` namespace of the unified
# FilesystemManager (Sprint 58.2). Routing every write through it makes the
# write atomic (temp+fsync+replace — no torn reads) and path-confined (the slug
# becomes a confined relative path; ``..``/absolute/traversal is rejected).
SEO_NAMESPACE = "seo"


class SeoPrerenderWriter:
    """Writes/removes prerender files on content.changed.

    ``post_loader.load(post_id)`` must return ``(post, terms, siblings)`` or
    ``None`` (the post was hard-deleted). ``canonical_rewrite_checker(slug)``
    (optional) returns True when a routing rewrite shadows the canonical slug.

    File IO is routed through the core ``FilesystemManager``'s ``seo`` namespace
    (atomic writes, slug confinement). When no manager is injected one is built
    over ``var_dir`` so the ``seo`` namespace root is ``<var_dir>/seo`` — the
    exact on-disk location used before the 58.2 migration.
    """

    def __init__(
        self,
        var_dir: str,
        post_loader,
        canonical_rewrite_checker: Optional[Callable[[str], bool]] = None,
        asset_stamper: Optional[SeoAssetStamper] = None,
        style_css_resolver: Optional[Callable[[object], str]] = None,
        filesystem_manager: Optional[Any] = None,
        full_page_renderer: Optional[IFullPageRenderer] = None,
        global_head_html_resolver: Optional[Callable[[], str]] = None,
        minifier: Optional[PrerenderMinifier] = None,
    ) -> None:
        self._filesystem_manager = filesystem_manager or LocalFilesystemManager(
            var_root=var_dir
        )
        self._post_loader = post_loader
        self._rewrite_checker = canonical_rewrite_checker
        self._asset_stamper = asset_stamper or SeoAssetStamper(
            os.environ.get("VBWD_FE_DIST_DIR")
        )
        # Resolves the CSS a post renders with (its explicit/default style +
        # the page's own ``source_css``) so the static page is styled pre-
        # hydration. Injected (DI) — absent ⇒ no <style> emitted.
        self._style_css_resolver = style_css_resolver
        # Optional external renderer that returns the COMPLETE page HTML
        # (layout + content) captured from the live SPA. When it yields a page
        # we write it as-is; absent/None ⇒ the content-only document is used.
        self._full_page_renderer = full_page_renderer
        # Resolves the site-wide raw ``<head>`` HTML (site-verification tags,
        # analytics snippets) baked into every prerender just before ``</head>``
        # so non-JS crawlers see it. Read lazily (per render). Injected (DI) —
        # absent/empty ⇒ nothing is spliced (no stray marker).
        self._global_head_html_resolver = global_head_html_resolver
        # Optional minifier applied to the final content-only document just
        # before the write. Injected (DI) — absent/None ⇒ today's exact pretty-
        # printed bytes are emitted (behaviour-preserving default, Liskov-safe).
        self._minifier = minifier

    # ── event entry point ────────────────────────────────────────────────

    def handle_content_changed(self, event_data: dict) -> None:
        """React to a ``content.changed`` event payload."""
        post_id = event_data.get("post_id")
        loaded = self._post_loader.load(post_id) if post_id else None

        if loaded is None:
            # Post is gone (hard delete) — still clear any stale file by slug.
            self._remove(event_data.get("slug"))
            return

        post, terms, siblings = loaded
        canonical_slug = post.slug

        if post.status != POST_STATUS_PUBLISHED:
            self._remove(canonical_slug)
            return

        if self._rewrite_checker and self._rewrite_checker(canonical_slug):
            logger.warning(
                "[cms.seo] Skipping prerender for '%s': a context-dependent "
                "routing rewrite targets this canonical slug (cloaking).",
                canonical_slug,
            )
            return

        self._write(post, terms, siblings)

    # ── file ops ─────────────────────────────────────────────────────────

    def _write(self, post, terms, siblings) -> None:
        # Prefer the COMPLETE page HTML from the external renderer when one is
        # configured. The rendered HTML is captured from the live SPA and is
        # self-contained (already carries head meta + the hashed asset tags),
        # so it is written as-is; the content-only document below remains the
        # fallback when the renderer is absent/disabled/failed.
        rendered = (
            self._full_page_renderer.render_full_page(
                post.slug, getattr(post, "language", None)
            )
            if self._full_page_renderer
            else None
        )
        if isinstance(rendered, str) and rendered:
            # The full render is HTML too, so honour the same minify toggle the
            # content-only branch below applies (DRY: one minifier, both paths).
            if self._minifier is not None:
                rendered = self._minifier.minify(rendered)
            self._filesystem_manager.write_text(
                SEO_NAMESPACE, self._relative_path_for(post.slug), rendered
            )
            return

        searchable = page_is_search_visible(_ScopeView(post, terms))
        robots_override = None if searchable else NOINDEX_ROBOTS

        renderable = RenderablePost(
            post,
            siblings=[RenderableSibling(s.language, s.canonical_url) for s in siblings],
            robots_override=robots_override,
        )
        head_tags, json_ld = build_meta(renderable)
        document = self._render_document(post, head_tags, json_ld, robots_override)
        if self._minifier is not None:
            document = self._minifier.minify(document)

        # The slug becomes a confined relative path within the ``seo``
        # namespace; the manager rejects ``..``/absolute/traversal rather than
        # trusting the slug, and writes atomically (no torn reads).
        self._filesystem_manager.write_text(
            SEO_NAMESPACE, self._relative_path_for(post.slug), document
        )

    def _remove(self, slug: Optional[str]) -> None:
        if not slug:
            return
        self._filesystem_manager.delete(SEO_NAMESPACE, self._relative_path_for(slug))

    @staticmethod
    def _relative_path_for(slug: str) -> str:
        return f"{slug}.html"

    # ── document template ────────────────────────────────────────────────

    def _render_document(
        self, post, head_tags: List[str], json_ld: dict, robots_override
    ) -> str:
        payload = {
            "slug": post.slug,
            "title": post.title,
            "content_html": post.content_html or "",
            "seo": {
                "robots": robots_override or post.robots,
                "canonical_url": post.canonical_url,
                "meta_description": post.meta_description,
            },
        }
        head = "\n    ".join(_mark_ssr(tag) for tag in head_tags)
        json_ld_block = (
            '<script type="application/ld+json">'
            + json.dumps(json_ld, ensure_ascii=False)
            + "</script>"
        )
        # S47.2: the current build's content-hashed entry tags are stamped here
        # on publish (so the static page can boot the SPA) and re-stamped in
        # place on every frontend deploy via ``SeoAssetStamper.restamp_all``.
        # The marker-delimited block is what the re-stamp finds and replaces.
        asset_block = render_asset_block(self._asset_stamper.current_entry_tags())

        # Inline the resolved style CSS + the page's own source_css so the
        # static page is styled before the SPA hydrates (no FOUC; bots see it
        # styled). The SPA later injects its own page style on mount.
        style_block = ""
        if self._style_css_resolver is not None:
            css = (self._style_css_resolver(post) or "").strip()
            if css:
                style_block = f'\n    <style data-seo="ssr-style">{css}</style>'

        # Site-wide raw <head> HTML (site-verification/analytics), baked in just
        # before </head> so non-JS crawlers see it. Empty ⇒ nothing spliced.
        global_head_block = ""
        if self._global_head_html_resolver is not None:
            raw_head_html = (self._global_head_html_resolver() or "").strip()
            if raw_head_html:
                global_head_block = f"\n    {raw_head_html}"

        return (
            "<!DOCTYPE html>\n"
            '<html lang="' + (post.language or "en") + '">\n'
            "  <head>\n"
            '    <meta charset="utf-8" />\n'
            f"    {head}\n"
            f"    {json_ld_block}\n"
            f"    {asset_block}"
            f"{style_block}"
            f"{global_head_block}\n"
            "  </head>\n"
            "  <body>\n"
            f'    <div id="app">{post.content_html or ""}</div>\n'
            '    <script type="application/json" id="__POST__">'
            + json.dumps(payload, ensure_ascii=False)
            + "</script>\n"
            "  </body>\n"
            "</html>\n"
        )


def _mark_ssr(head_tag: str) -> str:
    """Tag a server-emitted ``<meta>``/``<link>`` with ``data-seo="ssr"``.

    The client meta-injection (47.2/47.3 ``injectSeoMeta``) keys off this marker
    to update head tags **in place** instead of appending duplicates. ``<title>``
    needs no marker — the client owns it via ``document.title``.
    """
    if 'data-seo="ssr"' in head_tag:
        return head_tag
    if head_tag.startswith("<meta") or head_tag.startswith("<link"):
        return head_tag.replace("/>", 'data-seo="ssr" />', 1)
    return head_tag


class _ScopeView:
    """Adapts (post, terms) into the duck-typed shape the predicate expects."""

    def __init__(self, post, terms) -> None:
        self.status = post.status
        self.seo_excluded = post.seo_excluded
        self.robots = post.robots
        self.terms = terms or []
