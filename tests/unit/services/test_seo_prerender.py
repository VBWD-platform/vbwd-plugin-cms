"""S47.1 — the Python-template prerender writer (status-driven).

On ``content.changed`` the writer renders ``${VAR_DIR}/seo/<canonical-slug>.html``
for a published post (head + body + ``__POST__`` payload), writes a noindex file
for an excluded-but-published post, writes nothing for private/draft/scheduled,
and removes the file on trash/unpublish/delete. Keyed by canonical slug; a
context-rewrite on a canonical indexed slug is skipped + logged.
"""
import json
import logging

from plugins.cms.src.services.seo_prerender import SeoPrerenderWriter
from plugins.cms.src.models.cms_post import (
    POST_STATUS_PUBLISHED,
    POST_STATUS_PRIVATE,
    POST_STATUS_DRAFT,
    POST_STATUS_SCHEDULED,
    POST_STATUS_TRASH,
)


class _Post:
    def __init__(self, **kwargs):
        self.id = kwargs.get("id", "p1")
        self.type = kwargs.get("type", "page")
        self.slug = kwargs.get("slug", "pricing")
        self.title = kwargs.get("title", "Pricing")
        self.content_html = kwargs.get("content_html", "<p>Plans</p>")
        self.status = kwargs.get("status", POST_STATUS_PUBLISHED)
        self.language = kwargs.get("language", "en")
        self.robots = kwargs.get("robots", "index,follow")
        self.seo_excluded = kwargs.get("seo_excluded", False)
        self.meta_title = kwargs.get("meta_title", "Pricing")
        self.meta_description = kwargs.get("meta_description", "Our plans")
        self.meta_keywords = kwargs.get("meta_keywords", None)
        self.og_title = kwargs.get("og_title", None)
        self.og_description = kwargs.get("og_description", None)
        self.og_image_url = kwargs.get("og_image_url", None)
        self.canonical_url = kwargs.get("canonical_url", "https://x/pricing")
        self.schema_json = kwargs.get("schema_json", None)
        self.translation_group_id = kwargs.get("translation_group_id", None)
        self.terms = kwargs.get("terms", [])


class _Loader:
    """Test double: maps post_id → (_Post, terms, siblings)."""

    def __init__(self, posts):
        self._posts = {p.id: p for p in posts}

    def load(self, post_id):
        post = self._posts.get(post_id)
        if post is None:
            return None
        return post, post.terms, []


def _writer(tmp_path, posts, **kwargs):
    return SeoPrerenderWriter(
        var_dir=str(tmp_path),
        post_loader=_Loader(posts),
        **kwargs,
    )


def _seo_file(tmp_path, slug):
    return tmp_path / "seo" / f"{slug}.html"


def _event(post):
    return {
        "post_id": post.id,
        "type": post.type,
        "slug": post.slug,
        "status": post.status,
        "reason": "status_changed",
    }


def test_published_writes_head_body_and_payload(tmp_path):
    post = _Post()
    writer = _writer(tmp_path, [post])
    writer.handle_content_changed(_event(post))

    path = _seo_file(tmp_path, "pricing")
    assert path.exists()
    html = path.read_text()
    assert "<head>" in html
    assert "<title>Pricing</title>" in html
    assert '<div id="app"><p>Plans</p></div>' in html
    assert 'id="__POST__"' in html


def test_inlines_resolved_style_css_when_resolver_present(tmp_path):
    post = _Post(content_html="<p>Body</p>")
    writer = _writer(
        tmp_path,
        [post],
        style_css_resolver=lambda p: ".hero{color:red}",
    )
    writer.handle_content_changed(_event(post))
    html = _seo_file(tmp_path, "pricing").read_text()
    assert '<style data-seo="ssr-style">.hero{color:red}</style>' in html


def test_no_style_block_without_resolver(tmp_path):
    post = _Post()
    writer = _writer(tmp_path, [post])  # no resolver
    writer.handle_content_changed(_event(post))
    assert 'data-seo="ssr-style"' not in _seo_file(tmp_path, "pricing").read_text()


def test_empty_resolved_css_emits_no_style_block(tmp_path):
    post = _Post()
    writer = _writer(tmp_path, [post], style_css_resolver=lambda p: "")
    writer.handle_content_changed(_event(post))
    assert 'data-seo="ssr-style"' not in _seo_file(tmp_path, "pricing").read_text()


def test_published_embeds_entry_tags_between_markers(tmp_path):
    from plugins.cms.src.services.seo_asset_stamp import (
        ASSETS_BEGIN_MARKER,
        ASSETS_END_MARKER,
    )

    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text(
        "<html><head>"
        '<script type="module" src="/assets/index-deadbeef.js"></script>'
        '<link rel="stylesheet" href="/assets/index-cafe.css" />'
        "</head><body></body></html>"
    )
    from plugins.cms.src.services.seo_asset_stamp import SeoAssetStamper

    post = _Post()
    writer = _writer(tmp_path, [post], asset_stamper=SeoAssetStamper(str(dist)))
    writer.handle_content_changed(_event(post))

    html = _seo_file(tmp_path, "pricing").read_text()
    assert ASSETS_BEGIN_MARKER in html
    assert ASSETS_END_MARKER in html
    begin = html.index(ASSETS_BEGIN_MARKER)
    end = html.index(ASSETS_END_MARKER)
    block = html[begin:end]
    assert "/assets/index-deadbeef.js" in block
    assert "/assets/index-cafe.css" in block

    payload_start = html.index('id="__POST__">') + len('id="__POST__">')
    payload_end = html.index("</script>", payload_start)
    payload = json.loads(html[payload_start:payload_end])
    assert payload["slug"] == "pricing"
    assert payload["title"] == "Pricing"
    assert payload["content_html"] == "<p>Plans</p>"
    assert "seo" in payload


def test_global_head_html_injected_before_head_close(tmp_path):
    """A configured global head snippet is spliced into <head> before </head>.

    This is the crawler-visible home for site-verification tags (Bing
    ``msvalidate.01``) and analytics snippets: baked into the static bytes,
    site-wide, so non-JS bots see it (unlike the client-injected layout
    ``head_html``).
    """
    snippet = '<meta name="msvalidate.01" content="TESTKEY" />'
    post = _Post()
    writer = _writer(tmp_path, [post], global_head_html_resolver=lambda: snippet)
    writer.handle_content_changed(_event(post))

    html = _seo_file(tmp_path, "pricing").read_text()
    assert snippet in html
    assert html.index("<head>") < html.index(snippet) < html.index("</head>")


def test_global_head_html_empty_leaves_head_unchanged(tmp_path):
    post = _Post()
    writer = _writer(tmp_path, [post], global_head_html_resolver=lambda: "")
    writer.handle_content_changed(_event(post))

    html = _seo_file(tmp_path, "pricing").read_text()
    assert "msvalidate" not in html


def test_no_global_head_html_block_without_resolver(tmp_path):
    post = _Post()
    writer = _writer(tmp_path, [post])  # no resolver injected
    writer.handle_content_changed(_event(post))

    html = _seo_file(tmp_path, "pricing").read_text()
    assert "msvalidate" not in html


def test_private_writes_nothing(tmp_path):
    post = _Post(status=POST_STATUS_PRIVATE)
    writer = _writer(tmp_path, [post])
    writer.handle_content_changed(_event(post))
    assert not _seo_file(tmp_path, "pricing").exists()


def test_draft_and_scheduled_write_nothing(tmp_path):
    for status in (POST_STATUS_DRAFT, POST_STATUS_SCHEDULED):
        post = _Post(status=status)
        writer = _writer(tmp_path, [post])
        writer.handle_content_changed(_event(post))
        assert not _seo_file(tmp_path, "pricing").exists()


def test_trash_removes_existing_file(tmp_path):
    post = _Post()
    writer = _writer(tmp_path, [post])
    writer.handle_content_changed(_event(post))
    assert _seo_file(tmp_path, "pricing").exists()

    post.status = POST_STATUS_TRASH
    writer.handle_content_changed(_event(post))
    assert not _seo_file(tmp_path, "pricing").exists()


def test_unpublish_to_draft_removes_file(tmp_path):
    post = _Post()
    writer = _writer(tmp_path, [post])
    writer.handle_content_changed(_event(post))
    assert _seo_file(tmp_path, "pricing").exists()

    post.status = POST_STATUS_DRAFT
    writer.handle_content_changed(_event(post))
    assert not _seo_file(tmp_path, "pricing").exists()


def test_excluded_post_still_writes_with_noindex(tmp_path):
    post = _Post(seo_excluded=True)
    writer = _writer(tmp_path, [post])
    writer.handle_content_changed(_event(post))

    path = _seo_file(tmp_path, "pricing")
    assert path.exists()
    html = path.read_text()
    assert 'content="noindex,nofollow"' in html


def test_keyed_by_canonical_slug_with_nested_path(tmp_path):
    post = _Post(slug="about/team", canonical_url="https://x/about/team")
    writer = _writer(tmp_path, [post])
    writer.handle_content_changed(_event(post))
    assert _seo_file(tmp_path, "about/team").exists()


def test_context_rewrite_on_canonical_is_skipped_and_logged(tmp_path, caplog):
    post = _Post()

    def rewrites_canonical(slug):
        return True

    writer = _writer(tmp_path, [post], canonical_rewrite_checker=rewrites_canonical)
    with caplog.at_level(logging.WARNING):
        writer.handle_content_changed(_event(post))

    assert not _seo_file(tmp_path, "pricing").exists()
    assert any("rewrite" in record.message.lower() for record in caplog.records)


def test_prerender_head_has_no_snippet_block(tmp_path):
    """The snippet subsystem is removed — no snippet marker leaks into the head.

    Snippets are a front-end widget now, not a backend bake. The prerender
    document reverts to the S47.1 head (meta + json-ld + asset block) with no
    ``<!--vbwd:snippets:*-->`` marker and no CSP-from-snippets meta.
    """
    post = _Post()
    writer = _writer(tmp_path, [post])
    writer.handle_content_changed(_event(post))

    html = _seo_file(tmp_path, "pricing").read_text()
    assert "vbwd:snippets:" not in html
    assert "Content-Security-Policy" not in html


class _StubFullPageRenderer:
    """Test double for IFullPageRenderer: records calls, returns canned HTML."""

    def __init__(self, result):
        self._result = result
        self.calls = []

    def render_full_page(self, slug, language):
        self.calls.append((slug, language))
        return self._result


_FULL_PAGE_HTML = (
    '<!doctype html><html lang="en"><head><title>Pricing</title></head>'
    '<body><header class="site-nav">NAV</header>'
    "<main><p>Plans</p></main><footer>FOOT</footer></body></html>"
)


def test_full_page_renderer_output_is_written_verbatim(tmp_path):
    post = _Post()
    renderer = _StubFullPageRenderer(_FULL_PAGE_HTML)
    writer = _writer(tmp_path, [post], full_page_renderer=renderer)
    writer.handle_content_changed(_event(post))

    html = _seo_file(tmp_path, "pricing").read_text()
    # The complete rendered page is written as-is (layout incl.) ...
    assert html == _FULL_PAGE_HTML
    # ... not the content-only document.
    assert 'id="__POST__"' not in html
    assert '<div id="app"><p>Plans</p></div>' not in html
    # The renderer was asked for the canonical slug + language.
    assert renderer.calls == [("pricing", "en")]


def test_falls_back_to_content_document_when_renderer_returns_none(tmp_path):
    post = _Post()
    renderer = _StubFullPageRenderer(None)
    writer = _writer(tmp_path, [post], full_page_renderer=renderer)
    writer.handle_content_changed(_event(post))

    html = _seo_file(tmp_path, "pricing").read_text()
    assert '<div id="app"><p>Plans</p></div>' in html
    assert 'id="__POST__"' in html


def test_content_document_unchanged_when_no_renderer_injected(tmp_path):
    post = _Post()
    writer = _writer(tmp_path, [post])  # full_page_renderer defaults to None
    writer.handle_content_changed(_event(post))

    html = _seo_file(tmp_path, "pricing").read_text()
    assert '<div id="app"><p>Plans</p></div>' in html
    assert 'id="__POST__"' in html


_FULL_PAGE_HTML_PRETTY = (
    "<!doctype html>\n"
    '<html lang="en">\n'
    "  <head>\n"
    "    <title>Pricing</title>\n"
    "    <style>  .hero {\n    color: red;\n  }\n</style>\n"
    "  </head>\n"
    "  <body>\n"
    "    <header>NAV</header>\n"
    "    <main><p>Plans</p></main>\n"
    "  </body>\n"
    "</html>\n"
)


def test_full_render_output_is_minified_when_flag_on(tmp_path):
    """S118: the full-render HTML is minified too when the minify flag is on."""
    from plugins.cms.src.services.prerender_minifier import PrerenderMinifier

    post = _Post()
    renderer = _StubFullPageRenderer(_FULL_PAGE_HTML_PRETTY)
    writer = _writer(
        tmp_path, [post], full_page_renderer=renderer, minifier=PrerenderMinifier()
    )
    writer.handle_content_changed(_event(post))

    html = _seo_file(tmp_path, "pricing").read_text()
    # Inter-tag whitespace collapsed (no indented head line survives) ...
    assert "\n  <head>\n" not in html
    # ... and the inline style body is CSS-minified (structural whitespace gone).
    assert ".hero{" in html
    assert "  color: red;\n  }" not in html


def test_full_render_output_untouched_when_flag_off(tmp_path):
    """No minifier injected ⇒ the full render is written byte-for-byte as-is."""
    post = _Post()
    renderer = _StubFullPageRenderer(_FULL_PAGE_HTML_PRETTY)
    writer = _writer(tmp_path, [post], full_page_renderer=renderer)  # minifier None
    writer.handle_content_changed(_event(post))

    html = _seo_file(tmp_path, "pricing").read_text()
    assert html == _FULL_PAGE_HTML_PRETTY


def test_writer_emits_pretty_html_when_minify_off(tmp_path):
    """No minifier injected ⇒ today's pretty-printed, indented document."""
    post = _Post()
    writer = _writer(tmp_path, [post])  # minifier defaults to None
    writer.handle_content_changed(_event(post))

    html = _seo_file(tmp_path, "pricing").read_text()
    # The baseline document keeps its newlines + indentation (unchanged).
    assert "\n  <head>\n" in html
    assert html.endswith("</html>\n")


def test_writer_emits_minified_html_when_minify_on(tmp_path):
    from plugins.cms.src.services.prerender_minifier import PrerenderMinifier

    post = _Post()
    writer = _writer(
        tmp_path,
        [post],
        style_css_resolver=lambda p: "  .hero {\n    color: red;\n  }\n",
        minifier=PrerenderMinifier(),
    )
    writer.handle_content_changed(_event(post))

    html = _seo_file(tmp_path, "pricing").read_text()
    # Inter-tag whitespace collapsed (no indented head line survives) ...
    assert "\n  <head>\n" not in html
    # ... and the inline SSR style body is CSS-minified.
    assert ".hero{" in html
    # The page still boots the SPA (payload preserved).
    assert 'id="__POST__"' in html


def test_global_head_html_still_injected_under_minify(tmp_path):
    from plugins.cms.src.services.prerender_minifier import PrerenderMinifier

    snippet = '<meta name="msvalidate.01" content="TESTKEY" />'
    post = _Post()
    writer = _writer(
        tmp_path,
        [post],
        global_head_html_resolver=lambda: snippet,
        minifier=PrerenderMinifier(),
    )
    writer.handle_content_changed(_event(post))

    html = _seo_file(tmp_path, "pricing").read_text()
    # The verification snippet survives minification byte-exact, in <head>.
    assert snippet in html
    assert html.index("<head>") < html.index(snippet) < html.index("</head>")


def test_ld_json_and_post_payload_survive_minify_byte_exact(tmp_path):
    from plugins.cms.src.services.prerender_minifier import PrerenderMinifier

    post = _Post(content_html="<p>  spaced  body  </p>")
    writer = _writer(tmp_path, [post], minifier=PrerenderMinifier())
    writer.handle_content_changed(_event(post))

    html = _seo_file(tmp_path, "pricing").read_text()
    payload_start = html.index('id="__POST__">') + len('id="__POST__">')
    payload_end = html.index("</script>", payload_start)
    payload = json.loads(html[payload_start:payload_end])
    assert payload["slug"] == "pricing"
    assert payload["content_html"] == "<p>  spaced  body  </p>"


def test_missing_post_is_a_noop(tmp_path):
    writer = _writer(tmp_path, [])
    # Event references a post the loader can't find (e.g. hard-deleted).
    writer.handle_content_changed(
        {"post_id": "gone", "slug": "pricing", "status": POST_STATUS_TRASH}
    )
    # Trash/delete must still remove any stale file keyed by the event slug.
    assert not _seo_file(tmp_path, "pricing").exists()
