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


def test_missing_post_is_a_noop(tmp_path):
    writer = _writer(tmp_path, [])
    # Event references a post the loader can't find (e.g. hard-deleted).
    writer.handle_content_changed(
        {"post_id": "gone", "slug": "pricing", "status": POST_STATUS_TRASH}
    )
    # Trash/delete must still remove any stale file keyed by the event slug.
    assert not _seo_file(tmp_path, "pricing").exists()
