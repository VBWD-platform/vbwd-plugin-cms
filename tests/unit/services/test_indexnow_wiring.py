"""IndexNow wiring — the ``content.changed`` subscriber that pings IndexNow.

On a ``content.changed`` event for a PUBLISHED post the subscriber derives the
public path (same ``_public_path_for_slug`` the render-cache invalidator uses,
DRY) and calls the submitter. It is a no-op unless IndexNow is available
(enabled AND key non-empty AND ``public_base_url`` set) and the post is
published, mirroring the ``seo_dynamic_render_available()`` guard style. The
submitter + guard are monkeypatched so no config store / DB / network is needed.

Engineering requirements (binding, restated): TDD-first; SOLID/DI/DRY; Liskov
(guarded no-op, never crashes the publish flow); clean code; no overengineering.
Guard: ``bin/pre-commit-check.sh --plugin cms --full``.
"""
from unittest.mock import MagicMock

from plugins.cms.src.services import seo_wiring


def _published(slug="pricing"):
    return {"post_id": "1", "type": "page", "slug": slug, "status": "published"}


def test_content_changed_published_submits_url(monkeypatch):
    submitter = MagicMock()
    monkeypatch.setattr(seo_wiring, "indexnow_available", lambda: True)
    monkeypatch.setattr(seo_wiring, "build_indexnow_submitter", lambda: submitter)

    seo_wiring._on_content_changed_indexnow("content.changed", _published("pricing"))

    submitter.submit.assert_called_once_with("/pricing")


def test_content_changed_home_slug_submits_root(monkeypatch):
    submitter = MagicMock()
    monkeypatch.setattr(seo_wiring, "indexnow_available", lambda: True)
    monkeypatch.setattr(seo_wiring, "build_indexnow_submitter", lambda: submitter)

    seo_wiring._on_content_changed_indexnow("content.changed", _published(""))

    submitter.submit.assert_called_once_with("/")


def test_content_changed_draft_does_not_submit(monkeypatch):
    submitter = MagicMock()
    monkeypatch.setattr(seo_wiring, "indexnow_available", lambda: True)
    monkeypatch.setattr(seo_wiring, "build_indexnow_submitter", lambda: submitter)

    seo_wiring._on_content_changed_indexnow(
        "content.changed",
        {"post_id": "1", "slug": "draft-one", "status": "draft"},
    )

    submitter.submit.assert_not_called()


def test_no_submit_when_indexnow_disabled(monkeypatch):
    submitter = MagicMock()
    monkeypatch.setattr(seo_wiring, "indexnow_available", lambda: False)
    monkeypatch.setattr(seo_wiring, "build_indexnow_submitter", lambda: submitter)

    seo_wiring._on_content_changed_indexnow("content.changed", _published("pricing"))

    submitter.submit.assert_not_called()


def test_submit_failure_is_swallowed(monkeypatch):
    submitter = MagicMock()
    submitter.submit.side_effect = RuntimeError("boom")
    monkeypatch.setattr(seo_wiring, "indexnow_available", lambda: True)
    monkeypatch.setattr(seo_wiring, "build_indexnow_submitter", lambda: submitter)

    # Best-effort: a failing submitter must never propagate out of the callback.
    seo_wiring._on_content_changed_indexnow("content.changed", _published("pricing"))


# ── S154 D7: a switched-off content type is never pinged ─────────────────────


def test_switched_off_post_type_is_not_submitted(monkeypatch):
    submitter = MagicMock()
    monkeypatch.setattr(seo_wiring, "indexnow_available", lambda: True)
    monkeypatch.setattr(seo_wiring, "build_indexnow_submitter", lambda: submitter)
    monkeypatch.setattr(
        seo_wiring, "_sitemap_config", lambda: {"seo_index_pages": False}
    )

    event = dict(_published("pricing"), previous_slug="old-pricing")
    seo_wiring._on_content_changed_indexnow("content.changed", event)

    submitter.submit.assert_not_called()


def test_other_type_still_submitted_when_one_type_is_off(monkeypatch):
    submitter = MagicMock()
    monkeypatch.setattr(seo_wiring, "indexnow_available", lambda: True)
    monkeypatch.setattr(seo_wiring, "build_indexnow_submitter", lambda: submitter)
    monkeypatch.setattr(
        seo_wiring, "_sitemap_config", lambda: {"seo_index_pages": False}
    )

    event = dict(_published("news-item"), type="post")
    seo_wiring._on_content_changed_indexnow("content.changed", event)

    submitter.submit.assert_called_once_with("/news-item")


# ── ping_indexnow_urls (S154 D4) — the stable seam domain plugins call ──────
#
# shop/booking/subscription/ghrm import this (lazily, guarded by ImportError
# when cms is absent) instead of talking to ``IndexNowSubmitter`` directly, so
# cms stays the single home for the "is IndexNow available?" + "build the
# submitter" decisions (DRY) and never imports a domain plugin (D3-style).


def test_ping_indexnow_urls_submits_the_batch_when_available(monkeypatch):
    submitter = MagicMock()
    monkeypatch.setattr(seo_wiring, "indexnow_available", lambda: True)
    monkeypatch.setattr(seo_wiring, "build_indexnow_submitter", lambda: submitter)

    seo_wiring.ping_indexnow_urls(["/shop/product/mug", "/shop/product/cup"])

    submitter.submit_many.assert_called_once_with(
        ["/shop/product/mug", "/shop/product/cup"]
    )


def test_ping_indexnow_urls_noop_when_indexnow_unavailable(monkeypatch):
    submitter = MagicMock()
    monkeypatch.setattr(seo_wiring, "indexnow_available", lambda: False)
    monkeypatch.setattr(seo_wiring, "build_indexnow_submitter", lambda: submitter)

    result = seo_wiring.ping_indexnow_urls(["/shop/product/mug"])

    assert result is None
    submitter.submit_many.assert_not_called()


def test_ping_indexnow_urls_noop_when_no_paths(monkeypatch):
    submitter = MagicMock()
    monkeypatch.setattr(seo_wiring, "indexnow_available", lambda: True)
    monkeypatch.setattr(seo_wiring, "build_indexnow_submitter", lambda: submitter)

    assert seo_wiring.ping_indexnow_urls([]) is None
    assert seo_wiring.ping_indexnow_urls(["", None]) is None
    submitter.submit_many.assert_not_called()


def test_ping_indexnow_urls_swallows_submitter_failure(monkeypatch):
    submitter = MagicMock()
    submitter.submit_many.side_effect = RuntimeError("boom")
    monkeypatch.setattr(seo_wiring, "indexnow_available", lambda: True)
    monkeypatch.setattr(seo_wiring, "build_indexnow_submitter", lambda: submitter)

    # Best-effort: a failing submitter must never propagate to the caller.
    result = seo_wiring.ping_indexnow_urls(["/shop/product/mug"])

    assert result is False
