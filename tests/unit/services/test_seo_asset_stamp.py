"""S47.2 — the build-asset stamper (fills the 47.1 seam).

``current_entry_tags()`` reads the deployed fe-user build's ``index.html`` (or a
Vite ``manifest.json`` when present) and returns the current content-hashed
entry ``<script type="module">`` + CSS ``<link>`` tags so a prerendered file can
boot the SPA. When neither artifact is found it returns a safe, documented
fallback and logs — it never crashes the writer.

``restamp_all(seo_dir)`` rewrites the entry-tag block (delimited by stable HTML
comment markers) in every ``${VAR_DIR}/seo/*.html`` for the deploy hook. It is a
cheap string substitution and idempotent.
"""
import logging

from plugins.cms.src.services.seo_asset_stamp import (
    ASSETS_BEGIN_MARKER,
    ASSETS_END_MARKER,
    FALLBACK_ENTRY_TAGS,
    SeoAssetStamper,
)


def _write_index_html(dist_dir, script_src, css_href):
    dist_dir.mkdir(parents=True, exist_ok=True)
    (dist_dir / "index.html").write_text(
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "  <head>\n"
        '    <meta charset="utf-8" />\n'
        f'    <script type="module" crossorigin src="{script_src}"></script>\n'
        f'    <link rel="stylesheet" crossorigin href="{css_href}" />\n'
        "  </head>\n"
        '  <body><div id="app"></div></body>\n'
        "</html>\n"
    )


# ── current_entry_tags ───────────────────────────────────────────────────────


def test_current_entry_tags_reads_index_html(tmp_path):
    dist = tmp_path / "dist"
    _write_index_html(dist, "/assets/index-abc123.js", "/assets/index-def456.css")

    stamper = SeoAssetStamper(str(dist))
    tags = stamper.current_entry_tags()

    assert '<script type="module"' in tags
    assert "/assets/index-abc123.js" in tags
    assert '<link rel="stylesheet"' in tags
    assert "/assets/index-def456.css" in tags


def test_current_entry_tags_handles_index_without_css(tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir(parents=True)
    (dist / "index.html").write_text(
        "<html><head>"
        '<script type="module" src="/assets/index-xyz.js"></script>'
        "</head><body></body></html>"
    )
    stamper = SeoAssetStamper(str(dist))
    tags = stamper.current_entry_tags()
    assert "/assets/index-xyz.js" in tags
    assert "<link" not in tags


def test_current_entry_tags_prefers_manifest_when_present(tmp_path):
    dist = tmp_path / "dist"
    _write_index_html(dist, "/assets/index-old.js", "/assets/index-old.css")
    (dist / ".vite").mkdir(parents=True)
    (dist / ".vite" / "manifest.json").write_text(
        '{"index.html": {"isEntry": true,'
        ' "file": "assets/index-new.js",'
        ' "css": ["assets/index-new.css"]}}'
    )
    stamper = SeoAssetStamper(str(dist))
    tags = stamper.current_entry_tags()
    assert "/assets/index-new.js" in tags
    assert "/assets/index-new.css" in tags
    assert "old" not in tags


def test_current_entry_tags_safe_fallback_when_absent(tmp_path, caplog):
    stamper = SeoAssetStamper(str(tmp_path / "does-not-exist"))
    with caplog.at_level(logging.WARNING):
        tags = stamper.current_entry_tags()
    assert tags == FALLBACK_ENTRY_TAGS
    assert any("asset" in record.message.lower() for record in caplog.records)


def test_no_dist_dir_configured_returns_fallback():
    stamper = SeoAssetStamper(None)
    assert stamper.current_entry_tags() == FALLBACK_ENTRY_TAGS


# ── restamp_all ──────────────────────────────────────────────────────────────


def _seo_doc(entry_tags):
    return (
        "<!DOCTYPE html>\n<html><head><title>x</title>\n"
        f"    {ASSETS_BEGIN_MARKER}\n"
        f"    {entry_tags}\n"
        f"    {ASSETS_END_MARKER}\n"
        '</head><body><div id="app">hi</div></body></html>\n'
    )


def test_restamp_all_rewrites_entry_block(tmp_path):
    dist = tmp_path / "dist"
    _write_index_html(dist, "/assets/index-NEW.js", "/assets/index-NEW.css")
    seo_dir = tmp_path / "seo"
    seo_dir.mkdir()
    (seo_dir / "a.html").write_text(
        _seo_doc('<script type="module" src="/assets/index-OLD.js"></script>')
    )
    (seo_dir / "b.html").write_text(
        _seo_doc('<script type="module" src="/assets/index-OLD.js"></script>')
    )

    stamper = SeoAssetStamper(str(dist))
    rewritten = stamper.restamp_all(str(seo_dir))

    assert rewritten == 2
    for name in ("a.html", "b.html"):
        html = (seo_dir / name).read_text()
        assert "/assets/index-NEW.js" in html
        assert "OLD" not in html
        # Content body is untouched.
        assert '<div id="app">hi</div>' in html


def test_restamp_all_is_idempotent(tmp_path):
    dist = tmp_path / "dist"
    _write_index_html(dist, "/assets/index-V2.js", "/assets/index-V2.css")
    seo_dir = tmp_path / "seo"
    seo_dir.mkdir()
    (seo_dir / "a.html").write_text(
        _seo_doc('<script type="module" src="/assets/index-V1.js"></script>')
    )

    stamper = SeoAssetStamper(str(dist))
    stamper.restamp_all(str(seo_dir))
    first = (seo_dir / "a.html").read_text()
    stamper.restamp_all(str(seo_dir))
    second = (seo_dir / "a.html").read_text()

    assert first == second
    assert "/assets/index-V2.js" in second


def test_restamp_all_skips_files_without_markers(tmp_path):
    dist = tmp_path / "dist"
    _write_index_html(dist, "/assets/index-NEW.js", "/assets/index-NEW.css")
    seo_dir = tmp_path / "seo"
    seo_dir.mkdir()
    legacy = "<html><head></head><body>no markers</body></html>"
    (seo_dir / "legacy.html").write_text(legacy)

    stamper = SeoAssetStamper(str(dist))
    rewritten = stamper.restamp_all(str(seo_dir))

    assert rewritten == 0
    assert (seo_dir / "legacy.html").read_text() == legacy


def test_restamp_all_missing_dir_is_noop(tmp_path):
    dist = tmp_path / "dist"
    _write_index_html(dist, "/assets/index-NEW.js", "/assets/index-NEW.css")
    stamper = SeoAssetStamper(str(dist))
    assert stamper.restamp_all(str(tmp_path / "no-seo-dir")) == 0
