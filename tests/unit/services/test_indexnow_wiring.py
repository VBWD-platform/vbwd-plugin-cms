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
