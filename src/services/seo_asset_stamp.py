"""Build-asset stamper (S47.2 §4) — fills the 47.1 prerender seam.

A prerendered ``${VAR_DIR}/seo/<slug>.html`` must boot the live SPA after the
static first paint. To do that it needs the **content-hashed** entry tags of the
currently deployed fe-user build:

  - ``<script type="module" src="/assets/index-<hash>.js"></script>``
  - the matching CSS ``<link rel="stylesheet" href="/assets/index-<hash>.css">``

Those hashes change on every frontend deploy, so this module does two things:

  - ``current_entry_tags()`` reads the deployed build's ``index.html`` (or a Vite
    ``manifest.json`` when present) and returns the current entry tags. It is
    **best-effort**: when no artifact is found it returns a safe, documented
    fallback and logs — it must never crash the prerender writer.
  - ``restamp_all(seo_dir)`` rewrites the entry-tag block (delimited by the
    ``ASSETS_*`` markers) in every existing ``*.html``, for the deploy hook. It
    is a cheap string substitution (no content re-render) and idempotent.

The dist directory is configured via ``VBWD_FE_DIST_DIR`` (the path where the
deployed fe-user build is readable from the backend container).
"""
import json
import logging
import os
import re
from typing import List, Optional

logger = logging.getLogger(__name__)

# Stable markers delimit the stamped entry-tag block so ``restamp_all`` can find
# and replace it without re-rendering the content body.
ASSETS_BEGIN_MARKER = "<!--vbwd:assets-->"
ASSETS_END_MARKER = "<!--/vbwd:assets-->"

# Emitted when the deployed build cannot be located. Unhashed paths still let a
# dev/preview SPA boot; in prod the deploy re-stamp replaces them with the real
# hashed tags. Documented in the runbook (rollback section).
FALLBACK_ENTRY_TAGS = (
    '<script type="module" src="/assets/index.js"></script>\n'
    '    <link rel="stylesheet" href="/assets/index.css" />'
)

_MANIFEST_RELATIVE_PATHS = (
    os.path.join(".vite", "manifest.json"),
    "manifest.json",
)

_SCRIPT_SRC_PATTERN = re.compile(
    r'<script[^>]*\btype=["\']module["\'][^>]*\bsrc=["\']([^"\']+)["\']',
    re.IGNORECASE,
)
_STYLESHEET_HREF_PATTERN = re.compile(
    r'<link[^>]*\brel=["\']stylesheet["\'][^>]*\bhref=["\']([^"\']+)["\']',
    re.IGNORECASE,
)


def _script_tag(src: str) -> str:
    return f'<script type="module" src="{src}"></script>'


def _stylesheet_tag(href: str) -> str:
    return f'<link rel="stylesheet" href="{href}" />'


def _as_absolute_asset_url(path: str) -> str:
    """Vite manifest paths are build-root relative (``assets/x.js``)."""
    if path.startswith(("/", "http://", "https://")):
        return path
    return "/" + path.lstrip("/")


class SeoAssetStamper:
    """Sources + re-stamps the deployed build's hashed entry tags."""

    def __init__(self, dist_dir: Optional[str]) -> None:
        self._dist_dir = dist_dir

    # ── sourcing the current tags ────────────────────────────────────────

    def current_entry_tags(self) -> str:
        """Return the current build's entry ``<script>`` + CSS ``<link>`` tags.

        Best-effort: a Vite ``manifest.json`` is preferred (authoritative);
        otherwise the deployed ``index.html`` is parsed. Falls back to
        ``FALLBACK_ENTRY_TAGS`` (and logs) when neither is readable.
        """
        if not self._dist_dir:
            return FALLBACK_ENTRY_TAGS

        tags = self._tags_from_manifest() or self._tags_from_index_html()
        if tags is None:
            logger.warning(
                "[cms.seo] No fe-user build asset manifest/index.html under "
                "'%s'; using fallback entry tags. The SPA will boot only after "
                "the deploy re-stamp writes the hashed tags.",
                self._dist_dir,
            )
            return FALLBACK_ENTRY_TAGS
        return tags

    def _tags_from_manifest(self) -> Optional[str]:
        for relative in _MANIFEST_RELATIVE_PATHS:
            manifest_path = os.path.join(self._dist_dir or "", relative)
            if not os.path.isfile(manifest_path):
                continue
            try:
                with open(manifest_path, encoding="utf-8") as handle:
                    manifest = json.load(handle)
            except (OSError, ValueError) as error:
                logger.warning(
                    "[cms.seo] Unreadable Vite manifest '%s': %s",
                    manifest_path,
                    error,
                )
                return None
            return self._render_manifest_tags(manifest)
        return None

    def _render_manifest_tags(self, manifest: dict) -> Optional[str]:
        entry = next(
            (chunk for chunk in manifest.values() if chunk.get("isEntry")),
            None,
        )
        if not entry or not entry.get("file"):
            return None
        tags: List[str] = [_script_tag(_as_absolute_asset_url(entry["file"]))]
        for css_path in entry.get("css", []) or []:
            tags.append(_stylesheet_tag(_as_absolute_asset_url(css_path)))
        return "\n    ".join(tags)

    def _tags_from_index_html(self) -> Optional[str]:
        index_path = os.path.join(self._dist_dir or "", "index.html")
        if not os.path.isfile(index_path):
            return None
        try:
            with open(index_path, encoding="utf-8") as handle:
                html = handle.read()
        except OSError as error:
            logger.warning(
                "[cms.seo] Unreadable build index.html '%s': %s",
                index_path,
                error,
            )
            return None

        script_match = _SCRIPT_SRC_PATTERN.search(html)
        if not script_match:
            return None
        tags: List[str] = [_script_tag(script_match.group(1))]
        for css_match in _STYLESHEET_HREF_PATTERN.finditer(html):
            tags.append(_stylesheet_tag(css_match.group(1)))
        return "\n    ".join(tags)

    # ── re-stamping existing prerender files (deploy hook) ───────────────

    def restamp_all(self, seo_dir: str) -> int:
        """Rewrite the entry-tag block in every ``*.html`` under ``seo_dir``.

        Returns the number of files actually rewritten. Files without the
        ``ASSETS_*`` markers are skipped untouched; the operation is idempotent.
        """
        if not os.path.isdir(seo_dir):
            return 0

        entry_tags = self.current_entry_tags()
        rewritten = 0
        for root, _dirs, files in os.walk(seo_dir):
            for name in files:
                if not name.endswith(".html"):
                    continue
                if self._restamp_file(os.path.join(root, name), entry_tags):
                    rewritten += 1
        return rewritten

    def _restamp_file(self, path: str, entry_tags: str) -> bool:
        try:
            with open(path, encoding="utf-8") as handle:
                html = handle.read()
        except OSError as error:
            logger.warning("[cms.seo] Unreadable prerender file '%s': %s", path, error)
            return False

        replaced = render_asset_block(entry_tags)
        new_html = _replace_asset_block(html, replaced)
        if new_html is None or new_html == html:
            return False

        try:
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(new_html)
        except OSError as error:
            logger.warning(
                "[cms.seo] Could not rewrite prerender file '%s': %s", path, error
            )
            return False
        return True


def render_asset_block(entry_tags: str) -> str:
    """The full marker-delimited block embedded by the prerender writer."""
    return f"{ASSETS_BEGIN_MARKER}\n    {entry_tags}\n    {ASSETS_END_MARKER}"


def _replace_asset_block(html: str, replacement: str) -> Optional[str]:
    begin = html.find(ASSETS_BEGIN_MARKER)
    end = html.find(ASSETS_END_MARKER)
    if begin == -1 or end == -1 or end < begin:
        return None
    end_with_marker = end + len(ASSETS_END_MARKER)
    return html[:begin] + replacement + html[end_with_marker:]
