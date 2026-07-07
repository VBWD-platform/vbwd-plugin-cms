"""S122 §5a — the render-cache + IndexNow subscribers react to a rename.

On a ``content.changed`` payload that carries ``previous_slug`` (a permalink
moved), the render-cache invalidator must purge BOTH the new and the old public
path, and IndexNow must submit BOTH URLs (so engines recrawl the old URL and
pick up its 301). A payload without ``previous_slug`` touches only the new path.

Pure unit tests: the builders/availability gates are monkeypatched so no config,
DB, network, or dynamic-render service is required.

Engineering requirements (binding, restated): TDD-first; DevOps-first; SOLID/
DI/DRY; Liskov (no ``previous_slug`` ⇒ exactly today's single-path behaviour);
clean code; no overengineering. Quality guard:
``bin/pre-commit-check.sh --plugin cms --full``.
"""
from plugins.cms.src.services import seo_wiring
from plugins.cms.src.models.cms_post import POST_STATUS_PUBLISHED


class _FakeService:
    def __init__(self):
        self.invalidated = []

    def invalidate(self, path):
        self.invalidated.append(path)


class _FakeSubmitter:
    def __init__(self):
        self.submitted = []

    def submit(self, path):
        self.submitted.append(path)


def test_invalidate_purges_both_paths_on_rename(monkeypatch):
    service = _FakeService()
    monkeypatch.setattr(seo_wiring, "seo_dynamic_render_available", lambda: True)
    monkeypatch.setattr(seo_wiring, "build_dynamic_render_service", lambda: service)

    seo_wiring._on_content_changed_invalidate(
        "content.changed",
        {
            "slug": "blog/electronics/new-post",
            "previous_slug": "blog/electronics/old-post",
            "status": POST_STATUS_PUBLISHED,
        },
    )
    assert "/blog/electronics/new-post" in service.invalidated
    assert "/blog/electronics/old-post" in service.invalidated


def test_invalidate_single_path_without_previous_slug(monkeypatch):
    service = _FakeService()
    monkeypatch.setattr(seo_wiring, "seo_dynamic_render_available", lambda: True)
    monkeypatch.setattr(seo_wiring, "build_dynamic_render_service", lambda: service)

    seo_wiring._on_content_changed_invalidate(
        "content.changed",
        {"slug": "blog/electronics/my-post", "status": POST_STATUS_PUBLISHED},
    )
    assert service.invalidated == ["/blog/electronics/my-post"]


def test_indexnow_submits_both_urls_on_rename(monkeypatch):
    submitter = _FakeSubmitter()
    monkeypatch.setattr(seo_wiring, "indexnow_available", lambda: True)
    monkeypatch.setattr(seo_wiring, "build_indexnow_submitter", lambda: submitter)

    seo_wiring._on_content_changed_indexnow(
        "content.changed",
        {
            "slug": "blog/electronics/new-post",
            "previous_slug": "blog/electronics/old-post",
            "status": POST_STATUS_PUBLISHED,
        },
    )
    assert submitter.submitted == [
        "/blog/electronics/new-post",
        "/blog/electronics/old-post",
    ]


def test_indexnow_single_url_without_previous_slug(monkeypatch):
    submitter = _FakeSubmitter()
    monkeypatch.setattr(seo_wiring, "indexnow_available", lambda: True)
    monkeypatch.setattr(seo_wiring, "build_indexnow_submitter", lambda: submitter)

    seo_wiring._on_content_changed_indexnow(
        "content.changed",
        {"slug": "blog/electronics/my-post", "status": POST_STATUS_PUBLISHED},
    )
    assert submitter.submitted == ["/blog/electronics/my-post"]
