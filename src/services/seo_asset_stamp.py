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
from typing import Any, List, Optional

import requests

from vbwd.services.filesystem.local import LocalFilesystemManager

logger = logging.getLogger(__name__)

# The prerendered HTML re-stamped here lives under the ``seo`` namespace of the
# unified FilesystemManager (Sprint 58.2): reads + the atomic write-back both go
# through it so a concurrent re-prerender never observes a torn file.
SEO_NAMESPACE = "seo"

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

# Best-effort fetch of the live fe-user ``index.html`` when no local build dir is
# readable (prod, where ``VBWD_FE_DIST_DIR`` is unset). Short timeout so the
# prerender writer never blocks; failures degrade to the documented fallback.
_HTTP_FETCH_TIMEOUT_SECONDS = 5

# Sentinel distinguishing "HTTP not yet attempted" from a cached ``None`` result
# (HTTP attempted but produced no usable tags) so the fetch happens at most once.
_HTTP_TAGS_UNSET = object()

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


def _parse_html_tags(html: str) -> Optional[str]:
    """Build entry tags from an HTML document's module script + stylesheets.

    Single home (DRY) for parsing both the local ``index.html`` and the live
    HTTP one: returns ``None`` when no module ``<script>`` is present, else the
    ``_script_tag`` plus every matching ``_stylesheet_tag``, joined as the writer
    expects.
    """
    script_match = _SCRIPT_SRC_PATTERN.search(html)
    if not script_match:
        return None
    tags: List[str] = [_script_tag(script_match.group(1))]
    for css_match in _STYLESHEET_HREF_PATTERN.finditer(html):
        tags.append(_stylesheet_tag(css_match.group(1)))
    return "\n    ".join(tags)


def _as_absolute_asset_url(path: str) -> str:
    """Vite manifest paths are build-root relative (``assets/x.js``)."""
    if path.startswith(("/", "http://", "https://")):
        return path
    return "/" + path.lstrip("/")


class SeoAssetStamper:
    """Sources + re-stamps the deployed build's hashed entry tags.

    Re-stamping reads + writes the prerendered files through the core
    ``FilesystemManager``'s ``seo`` namespace (atomic write-back). When no
    manager is injected one is built per ``restamp_all`` call over the parent of
    the passed ``seo_dir`` so the ``seo`` namespace root equals ``seo_dir`` — the
    exact files re-stamped before the 58.2 migration.
    """

    def __init__(
        self,
        dist_dir: Optional[str],
        filesystem_manager: Optional[Any] = None,
        public_base_url: Optional[str] = None,
    ) -> None:
        self._dist_dir = dist_dir
        self._filesystem_manager = filesystem_manager
        self._public_base_url = public_base_url
        self._http_tags_cache: Any = _HTTP_TAGS_UNSET

    # ── sourcing the current tags ────────────────────────────────────────

    def current_entry_tags(self) -> str:
        """Return the current build's entry ``<script>`` + CSS ``<link>`` tags.

        Best-effort, in precedence order: a Vite ``manifest.json`` (preferred,
        authoritative), then the deployed ``index.html``, then the live fe-user
        ``index.html`` fetched over HTTP (prod, where no local build dir is
        readable). Falls back to ``FALLBACK_ENTRY_TAGS`` (and logs) when none of
        the three sources yields tags.
        """
        tags = (
            self._tags_from_manifest()
            or self._tags_from_index_html()
            or self._tags_from_http()
        )
        if tags is None:
            logger.warning(
                "[cms.seo] No fe-user build asset manifest/index.html under "
                "'%s' and no HTTP source resolved; using fallback entry tags. "
                "The SPA will boot only after the deploy re-stamp writes the "
                "hashed tags.",
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

        return _parse_html_tags(html)

    def _tags_from_http(self) -> Optional[str]:
        """Parse the live fe-user ``index.html`` over HTTP (best-effort).

        Used only when no local build dir is readable (prod, ``VBWD_FE_DIST_DIR``
        unset). The result (the parsed tags, or ``None``) is cached on the
        instance so ``restamp_all``'s per-file loop fetches at most once. Never
        raises: a missing ``public_base_url``, a non-200, or any request error
        degrades to ``None`` so the caller uses the documented fallback.
        """
        if self._http_tags_cache is not _HTTP_TAGS_UNSET:
            return self._http_tags_cache  # type: ignore[no-any-return]

        self._http_tags_cache = self._fetch_http_tags()
        return self._http_tags_cache  # type: ignore[no-any-return]

    def _fetch_http_tags(self) -> Optional[str]:
        if not self._public_base_url:
            return None
        url = self._public_base_url.rstrip("/") + "/"
        try:
            response = requests.get(url, timeout=_HTTP_FETCH_TIMEOUT_SECONDS)
        except Exception as error:  # best-effort: HTTP source must never raise
            logger.warning(
                "[cms.seo] Could not fetch live index.html '%s': %s", url, error
            )
            return None
        if response.status_code != 200:
            logger.warning(
                "[cms.seo] Live index.html '%s' returned HTTP %s; "
                "using fallback entry tags.",
                url,
                response.status_code,
            )
            return None
        return _parse_html_tags(response.text)

    # ── re-stamping existing prerender files (deploy hook) ───────────────

    def restamp_all(self, seo_dir: str) -> int:
        """Rewrite the entry-tag block in every ``*.html`` under ``seo_dir``.

        Returns the number of files actually rewritten. Files without the
        ``ASSETS_*`` markers are skipped untouched; the operation is idempotent.
        Reads + writes flow through the ``seo`` namespace so the write-back is
        atomic (no torn read against a concurrent re-prerender).
        """
        if not os.path.isdir(seo_dir):
            return 0

        filesystem_manager = self._resolve_manager(seo_dir)
        entry_tags = self.current_entry_tags()
        rewritten = 0
        for relative_path in iter_seo_html_relative_paths(filesystem_manager):
            if self._restamp_file(filesystem_manager, relative_path, entry_tags):
                rewritten += 1
        return rewritten

    def _resolve_manager(self, seo_dir: str) -> Any:
        if self._filesystem_manager is not None:
            return self._filesystem_manager
        # ``seo_dir`` is ``<var_root>/seo``; rooting the manager at its parent
        # makes the ``seo`` namespace resolve to exactly ``seo_dir``.
        return LocalFilesystemManager(var_root=os.path.dirname(seo_dir))

    def _restamp_file(
        self, filesystem_manager: Any, relative_path: str, entry_tags: str
    ) -> bool:
        try:
            html = filesystem_manager.read_text(SEO_NAMESPACE, relative_path)
        except OSError as error:
            logger.warning(
                "[cms.seo] Unreadable prerender file '%s': %s", relative_path, error
            )
            return False

        replaced = render_asset_block(entry_tags)
        new_html = _replace_asset_block(html, replaced)
        if new_html is None or new_html == html:
            return False

        try:
            filesystem_manager.write_text(SEO_NAMESPACE, relative_path, new_html)
        except OSError as error:
            logger.warning(
                "[cms.seo] Could not rewrite prerender file '%s': %s",
                relative_path,
                error,
            )
            return False
        return True


def iter_seo_html_relative_paths(filesystem_manager: Any) -> List[str]:
    """Every ``*.html`` rel-path under the ``seo`` namespace (recursive).

    ``listdir`` is non-recursive, so nested slug dirs (``de/preise.html``) are
    discovered by descending one level at a time. A child is a directory when
    its confined absolute path is a directory (``resolve`` never escapes the
    namespace), else it is a file. Shared by the re-stamper and the purge so the
    "which files are managed" rule has a single home (DRY).
    """
    html_paths: List[str] = []
    pending = [""]
    while pending:
        current = pending.pop()
        for name in filesystem_manager.listdir(SEO_NAMESPACE, current):
            child = f"{current}/{name}" if current else name
            absolute = filesystem_manager.resolve(SEO_NAMESPACE, child)
            if os.path.isdir(absolute):
                pending.append(child)
            elif name.endswith(".html"):
                html_paths.append(child)
    return html_paths


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
