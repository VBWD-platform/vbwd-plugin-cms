"""``regenerate_prerendered`` rebuilds a file for every published post.

The manual "Generate prerendered content" admin action writes directly via the
writer, so it runs regardless of the ``seo_prerender_enabled`` toggle (a
deliberate admin override) and returns the number of files written.
"""
from unittest.mock import MagicMock

from plugins.cms.src.services import seo_wiring


class _Post:
    def __init__(self, post_id):
        self.id = post_id


def test_regenerate_writes_one_per_published_post(monkeypatch):
    writer = MagicMock()
    monkeypatch.setattr(seo_wiring, "_build_writer", lambda: writer)
    loader = MagicMock()
    loader.iter_candidate_posts.return_value = [_Post("p1"), _Post("p2")]
    monkeypatch.setattr(seo_wiring, "SeoPostLoader", lambda _session: loader)
    monkeypatch.setattr(seo_wiring, "_session", lambda: None)

    written = seo_wiring.regenerate_prerendered()

    assert written == 2
    assert writer.handle_content_changed.call_count == 2
    writer.handle_content_changed.assert_any_call({"post_id": "p1"})
    writer.handle_content_changed.assert_any_call({"post_id": "p2"})


def test_regenerate_ignores_the_toggle(monkeypatch):
    # Even with prerendering switched off, a manual regenerate still writes.
    monkeypatch.setattr(seo_wiring, "_seo_prerender_enabled", lambda: False)
    writer = MagicMock()
    monkeypatch.setattr(seo_wiring, "_build_writer", lambda: writer)
    loader = MagicMock()
    loader.iter_candidate_posts.return_value = [_Post("p1")]
    monkeypatch.setattr(seo_wiring, "SeoPostLoader", lambda _session: loader)
    monkeypatch.setattr(seo_wiring, "_session", lambda: None)

    assert seo_wiring.regenerate_prerendered() == 1
    writer.handle_content_changed.assert_called_once_with({"post_id": "p1"})


def test_regenerate_zero_when_no_published(monkeypatch):
    monkeypatch.setattr(seo_wiring, "_build_writer", lambda: MagicMock())
    loader = MagicMock()
    loader.iter_candidate_posts.return_value = []
    monkeypatch.setattr(seo_wiring, "SeoPostLoader", lambda _session: loader)
    monkeypatch.setattr(seo_wiring, "_session", lambda: None)

    assert seo_wiring.regenerate_prerendered() == 0
