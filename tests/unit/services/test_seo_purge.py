"""``purge_prerendered`` removes every generated ``${VAR_DIR}/seo/*.html``.

The manual "Clean up prerendered content" admin action calls this so that,
once SEO prerendering is switched off, the stale static files stop being
served by nginx (which serves purely by file existence) and traffic falls
through to the SPA. Symmetric to ``restamp_prerendered_assets``.
"""
import os

from plugins.cms.src.services import seo_wiring


def _touch(path: str, body: str = "<html></html>") -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(body)


def test_purge_removes_all_html_recursively(tmp_path, monkeypatch):
    monkeypatch.setenv("VBWD_VAR_DIR", str(tmp_path))
    seo_dir = tmp_path / "seo"
    _touch(str(seo_dir / "about.html"))
    _touch(str(seo_dir / "pricing.html"))
    _touch(str(seo_dir / "de" / "preise.html"))  # nested slug

    removed = seo_wiring.purge_prerendered()

    assert removed == 3
    assert not (seo_dir / "about.html").exists()
    assert not (seo_dir / "de" / "preise.html").exists()


def test_purge_leaves_non_html_untouched(tmp_path, monkeypatch):
    monkeypatch.setenv("VBWD_VAR_DIR", str(tmp_path))
    seo_dir = tmp_path / "seo"
    _touch(str(seo_dir / "about.html"))
    _touch(str(seo_dir / "keep.txt"), "not a prerender file")

    removed = seo_wiring.purge_prerendered()

    assert removed == 1
    assert (seo_dir / "keep.txt").exists()


def test_purge_on_missing_dir_is_zero(tmp_path, monkeypatch):
    monkeypatch.setenv("VBWD_VAR_DIR", str(tmp_path))
    assert seo_wiring.purge_prerendered() == 0
