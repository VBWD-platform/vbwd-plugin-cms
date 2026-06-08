"""S58.2 — route SEO prerender file IO through the core FilesystemManager.

The legacy writers used ``os.makedirs`` + ``open(w)`` in place: a concurrent
``content.changed`` re-prerender of a slug could **truncate** the file mid-read,
so a reader saw a half-written page. This sprint routes every SEO write through
the ``seo`` namespace (``WriteMode.ATOMIC_REPLACE``) so writes are atomic
(temp+fsync+replace — no torn reads) and path-confined (slug → safe relative
path; ``..``/absolute/traversal rejected).

These tests assert the migration is **behaviour-identical** (same on-disk path,
same HTML bytes) and adds the new guarantee (no truncation under concurrency).
"""
import threading
import time

from plugins.cms.src.models.cms_post import POST_STATUS_PUBLISHED
from plugins.cms.src.services import seo_wiring
from plugins.cms.src.services.seo_asset_stamp import (
    ASSETS_BEGIN_MARKER,
    ASSETS_END_MARKER,
    SeoAssetStamper,
)
from plugins.cms.src.services.seo_prerender import SeoPrerenderWriter
from vbwd.services.filesystem.local import LocalFilesystemManager


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
        self.meta_keywords = None
        self.og_title = None
        self.og_description = None
        self.og_image_url = None
        self.canonical_url = kwargs.get("canonical_url", "https://x/pricing")
        self.schema_json = None
        self.translation_group_id = None
        self.terms = []


class _Loader:
    def __init__(self, posts):
        self._posts = {p.id: p for p in posts}

    def load(self, post_id):
        post = self._posts.get(post_id)
        if post is None:
            return None
        return post, post.terms, []


def _event(post):
    return {"post_id": post.id, "slug": post.slug, "status": post.status}


def _manager(var_dir) -> LocalFilesystemManager:
    return LocalFilesystemManager(var_root=str(var_dir))


# ── byte-identical migration ────────────────────────────────────────────────


def test_prerender_via_manager_is_byte_identical_simple_slug(tmp_path):
    """The manager-backed write produces the SAME path + SAME bytes as the
    legacy direct ``open(w)`` would for a simple slug."""
    post = _Post(slug="pricing")

    legacy_dir = tmp_path / "legacy"
    manager_dir = tmp_path / "managed"

    legacy_writer = SeoPrerenderWriter(
        var_dir=str(legacy_dir), post_loader=_Loader([post])
    )
    manager_writer = SeoPrerenderWriter(
        var_dir=str(manager_dir),
        post_loader=_Loader([post]),
        filesystem_manager=_manager(manager_dir),
    )

    legacy_writer.handle_content_changed(_event(post))
    manager_writer.handle_content_changed(_event(post))

    legacy_bytes = (legacy_dir / "seo" / "pricing.html").read_bytes()
    managed_bytes = (manager_dir / "seo" / "pricing.html").read_bytes()
    assert managed_bytes == legacy_bytes


def test_prerender_via_manager_is_byte_identical_nested_child_slug(tmp_path):
    """A nested child slug keeps producing ``seo/parent/child.html`` with the
    SAME bytes through the manager."""
    post = _Post(slug="about/team", canonical_url="https://x/about/team")

    legacy_dir = tmp_path / "legacy"
    manager_dir = tmp_path / "managed"

    SeoPrerenderWriter(
        var_dir=str(legacy_dir), post_loader=_Loader([post])
    ).handle_content_changed(_event(post))
    SeoPrerenderWriter(
        var_dir=str(manager_dir),
        post_loader=_Loader([post]),
        filesystem_manager=_manager(manager_dir),
    ).handle_content_changed(_event(post))

    legacy_file = legacy_dir / "seo" / "about" / "team.html"
    managed_file = manager_dir / "seo" / "about" / "team.html"
    assert managed_file.exists()
    assert managed_file.read_bytes() == legacy_file.read_bytes()


def test_prerender_remove_via_manager(tmp_path):
    post = _Post(slug="pricing")
    writer = SeoPrerenderWriter(
        var_dir=str(tmp_path),
        post_loader=_Loader([post]),
        filesystem_manager=_manager(tmp_path),
    )
    writer.handle_content_changed(_event(post))
    assert (tmp_path / "seo" / "pricing.html").exists()

    post.status = "trash"
    writer.handle_content_changed(_event(post))
    assert not (tmp_path / "seo" / "pricing.html").exists()


# ── headline: concurrent publish never yields a torn read ───────────────────


def test_concurrent_publish_never_truncates(tmp_path):
    """One writer repeatedly re-prerenders a slug while a reader repeatedly
    reads it; the reader must NEVER observe a truncated/empty/partial file.

    Under the legacy in-place ``open(w)`` this raced (the file is opened for
    truncation before the new bytes land). ATOMIC_REPLACE guarantees the reader
    always sees either the previous complete file or the next complete file.
    """
    post = _Post(slug="pricing")
    writer = SeoPrerenderWriter(
        var_dir=str(tmp_path),
        post_loader=_Loader([post]),
        filesystem_manager=_manager(tmp_path),
    )
    # Prime a first complete file so the reader always has something to read.
    writer.handle_content_changed(_event(post))

    target = tmp_path / "seo" / "pricing.html"
    expected = target.read_text()
    assert expected  # non-empty baseline

    stop = threading.Event()
    observed_corruption = []

    def write_loop():
        for _ in range(300):
            if stop.is_set():
                return
            writer.handle_content_changed(_event(post))

    def read_loop():
        deadline = time.time() + 5.0
        while not stop.is_set() and time.time() < deadline:
            try:
                content = target.read_text()
            except FileNotFoundError:
                # ATOMIC_REPLACE keeps the target present at all times.
                observed_corruption.append("missing")
                return
            if content == "":
                observed_corruption.append("empty")
                return
            if not content.endswith("</html>\n"):
                observed_corruption.append("partial")
                return

    writer_thread = threading.Thread(target=write_loop)
    reader_thread = threading.Thread(target=read_loop)
    writer_thread.start()
    reader_thread.start()
    writer_thread.join()
    stop.set()
    reader_thread.join()

    assert observed_corruption == []


# ── asset re-stamp round-trips through the manager ──────────────────────────


def _seo_doc(entry_tags):
    return (
        "<!DOCTYPE html>\n<html><head><title>x</title>\n"
        f"    {ASSETS_BEGIN_MARKER}\n"
        f"    {entry_tags}\n"
        f"    {ASSETS_END_MARKER}\n"
        '</head><body><div id="app">hi</div></body></html>\n'
    )


def _write_index_html(dist_dir, script_src, css_href):
    dist_dir.mkdir(parents=True, exist_ok=True)
    (dist_dir / "index.html").write_text(
        "<html><head>"
        f'<script type="module" src="{script_src}"></script>'
        f'<link rel="stylesheet" href="{css_href}" />'
        "</head><body></body></html>"
    )


def test_restamp_via_manager_round_trips(tmp_path):
    dist = tmp_path / "dist"
    _write_index_html(dist, "/assets/index-NEW.js", "/assets/index-NEW.css")
    seo_dir = tmp_path / "seo"
    seo_dir.mkdir()
    (seo_dir / "a.html").write_text(
        _seo_doc('<script type="module" src="/assets/index-OLD.js"></script>')
    )
    (seo_dir / "de").mkdir()
    (seo_dir / "de" / "b.html").write_text(
        _seo_doc('<script type="module" src="/assets/index-OLD.js"></script>')
    )

    stamper = SeoAssetStamper(str(dist), filesystem_manager=_manager(tmp_path))
    rewritten = stamper.restamp_all(str(seo_dir))

    assert rewritten == 2
    top = (seo_dir / "a.html").read_text()
    nested = (seo_dir / "de" / "b.html").read_text()
    assert "/assets/index-NEW.js" in top
    assert "OLD" not in top
    assert "/assets/index-NEW.js" in nested
    assert "OLD" not in nested


def test_restamp_via_manager_missing_dir_is_noop(tmp_path):
    dist = tmp_path / "dist"
    _write_index_html(dist, "/assets/index-NEW.js", "/assets/index-NEW.css")
    stamper = SeoAssetStamper(str(dist), filesystem_manager=_manager(tmp_path))
    assert stamper.restamp_all(str(tmp_path / "no-seo-dir")) == 0


# ── purge through the manager + confinement ─────────────────────────────────


def test_purge_via_manager_removes_expected_files(tmp_path, monkeypatch):
    monkeypatch.setenv("VBWD_VAR_DIR", str(tmp_path))
    seo_dir = tmp_path / "seo"
    (seo_dir / "de").mkdir(parents=True)
    (seo_dir / "about.html").write_text("<html></html>")
    (seo_dir / "pricing.html").write_text("<html></html>")
    (seo_dir / "de" / "preise.html").write_text("<html></html>")
    (seo_dir / "keep.txt").write_text("keep me")

    removed = seo_wiring.purge_prerendered()

    assert removed == 3
    assert not (seo_dir / "about.html").exists()
    assert not (seo_dir / "de" / "preise.html").exists()
    assert (seo_dir / "keep.txt").exists()


def test_traversal_slug_is_rejected_by_namespace_confinement(tmp_path):
    """A slug containing ``..`` must NOT escape the seo namespace — the manager
    raises rather than writing outside ``seo/``."""
    post = _Post(slug="../escape", canonical_url="https://x/escape")
    writer = SeoPrerenderWriter(
        var_dir=str(tmp_path),
        post_loader=_Loader([post]),
        filesystem_manager=_manager(tmp_path),
    )
    import pytest

    with pytest.raises(ValueError):
        writer.handle_content_changed(_event(post))

    # Nothing was written outside seo/.
    assert not (tmp_path / "escape.html").exists()
