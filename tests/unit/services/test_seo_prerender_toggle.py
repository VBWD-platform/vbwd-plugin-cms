"""The ``seo_prerender_enabled`` config toggle gates the prerender subscriber.

When the cms config has ``seo_prerender_enabled`` false, ``content.changed``
must NOT build/run the prerender writer (the app serves the SPA only). When
true — or absent (default on) — it runs as before. The toggle is read live per
event so flipping it in the admin UI takes effect without re-enabling.
"""
from unittest.mock import MagicMock

from plugins.cms.src.services import seo_wiring


def test_disabled_skips_prerender_write(monkeypatch):
    monkeypatch.setattr(seo_wiring, "_seo_prerender_enabled", lambda: False)
    writer_factory = MagicMock()
    monkeypatch.setattr(seo_wiring, "_build_writer", writer_factory)

    seo_wiring._on_content_changed("content.changed", {"id": "p1"})

    writer_factory.assert_not_called()


def test_enabled_runs_prerender_write(monkeypatch):
    monkeypatch.setattr(seo_wiring, "_seo_prerender_enabled", lambda: True)
    writer = MagicMock()
    monkeypatch.setattr(seo_wiring, "_build_writer", lambda: writer)

    payload = {"id": "p1"}
    seo_wiring._on_content_changed("content.changed", payload)

    writer.handle_content_changed.assert_called_once_with(payload)


def test_toggle_defaults_on_without_app_context(monkeypatch):
    # No flask app context → resolver must default to True (preserve behaviour).
    assert seo_wiring._seo_prerender_enabled() is True
