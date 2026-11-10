"""S154 D7 — the prerender writer obeys the per-type "indexable" switches.

A published page/post whose type is switched off (``seo_index_pages`` /
``seo_index_posts``) is still prerendered — a direct-link visitor keeps the
fast page — but it carries ``noindex,follow`` (links stay crawlable) in BOTH
branches: the content-only document (meta tag + ``__POST__`` payload) and the
captured full page. Private/excluded content still wins with
``noindex,nofollow``; with the type switched on nothing changes.

Engineering requirements (binding, restated): TDD-first; SOLID/DI (the
switches are injected, the writer never reads config); DRY (one robots rule,
``index_robots_override``); Liskov (no switches injected = today's output);
clean code; no overengineering. Guard: ``bin/pre-commit-check.sh --plugin cms
--full``.
"""
from plugins.cms.src.services.seo_index_switches import SeoIndexSwitches
from plugins.cms.src.services.seo_prerender import SeoPrerenderWriter

from plugins.cms.tests.unit.services.test_seo_prerender import (
    _FULL_PAGE_HTML,
    _Loader,
    _Post,
    _StubFullPageRenderer,
    _event,
    _seo_file,
)

_PAGES_OFF = SeoIndexSwitches(pages=False, posts=True, categories=False, tags=False)
_ALL_ON = SeoIndexSwitches(pages=True, posts=True, categories=True, tags=True)


def _write(tmp_path, post, **kwargs):
    writer = SeoPrerenderWriter(
        var_dir=str(tmp_path), post_loader=_Loader([post]), **kwargs
    )
    writer.handle_content_changed(_event(post))
    return _seo_file(tmp_path, post.slug).read_text()


def test_switched_off_page_is_noindex_follow_in_the_content_document(tmp_path):
    html = _write(tmp_path, _Post(type="page"), index_switches=_PAGES_OFF)

    assert '<meta name="robots" content="noindex,follow" data-seo="ssr" />' in html
    assert '"robots": "noindex,follow"' in html
    assert "index,follow" not in html.replace("noindex,follow", "")


def test_switched_off_page_is_forced_noindex_follow_in_the_full_page(tmp_path):
    renderer = _StubFullPageRenderer(
        _FULL_PAGE_HTML.replace(
            "<title>", '<meta name="robots" content="index,follow"><title>'
        )
    )
    html = _write(
        tmp_path,
        _Post(type="page"),
        index_switches=_PAGES_OFF,
        full_page_renderer=renderer,
    )

    assert html.count('name="robots"') == 1
    assert '<meta name="robots" content="noindex,follow" />' in html
    assert "<main><p>Plans</p></main>" in html


def test_a_post_is_untouched_when_only_pages_are_switched_off(tmp_path):
    html = _write(tmp_path, _Post(type="post", slug="news"), index_switches=_PAGES_OFF)

    assert 'content="index,follow"' in html
    assert "noindex" not in html


def test_switched_on_type_keeps_the_post_robots(tmp_path):
    html = _write(tmp_path, _Post(type="page"), index_switches=_ALL_ON)

    assert 'content="index,follow"' in html
    assert "noindex" not in html


def test_private_path_stays_noindex_nofollow_when_the_type_is_off(tmp_path):
    post = _Post(type="page", slug="dashboard", canonical_url="https://x/dashboard")
    html = _write(tmp_path, post, index_switches=_PAGES_OFF)

    assert 'content="noindex,nofollow"' in html
    assert "noindex,follow" not in html


def test_excluded_full_page_stays_noindex_nofollow_when_the_type_is_off(tmp_path):
    html = _write(
        tmp_path,
        _Post(type="page", seo_excluded=True),
        index_switches=_PAGES_OFF,
        full_page_renderer=_StubFullPageRenderer(_FULL_PAGE_HTML),
    )

    assert '<meta name="robots" content="noindex,nofollow" />' in html
