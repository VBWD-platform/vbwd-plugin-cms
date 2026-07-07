"""Edge-alignment patch for CMS style source_css.

Every CMS page/post must render with the header nav, breadcrumb and main
content all starting on one vertical line. That alignment is governed by an
``--edge-inset`` system. This module owns the canonical, marker-delimited
``VBWD_EDGE_ALIGN`` block and an idempotent helper that injects it into any
style's ``source_css``.

Design notes:
  * ``var(--edge-inset)`` is used WITHOUT a fallback on purpose. Styles that
    define ``--edge-inset`` (narrow / 1200 → 0rem, fullwidth → 1.5rem) use
    their own value; styles that do NOT define it leave the padding property
    invalid (guaranteed-invalid var on a non-inherited property → the property
    computes to its initial value, 0). This is why we must NOT add a
    top-level ``:root { --edge-inset: 0 }`` line here — that would override
    fullwidth themes' 1.5rem.
  * ``.cms-area--content .container`` (the main post/page body) is
    deliberately EXCLUDED from that shared ``--edge-inset`` group and gets its
    own fixed ``1.5rem`` gutter instead. On narrow/1200 themes
    ``--edge-inset`` is ``0rem``, which is correct for widgets that already
    sit inside the viewport-centred max-width column, but would leave body
    copy with zero horizontal padding — unreadable text kissing the
    container edge. A readable gutter must not depend on the theme's
    edge-inset value.
  * The block is delimited by start/end markers so re-applying replaces the
    block in place rather than duplicating it. Everything outside the markers
    (colours, fonts, the rest of the theme look) is left untouched.
"""
from __future__ import annotations

import re
from typing import Optional

EDGE_ALIGN_VERSION = "v2"
EDGE_ALIGN_START_MARKER = (
    "/* VBWD_EDGE_ALIGN:v2 — header nav, breadcrumb + content on one "
    "vertical line. Do not edit by hand. */"
)
EDGE_ALIGN_END_MARKER = "/* /VBWD_EDGE_ALIGN:v2 */"

# Each CSS rule is one logical CSS line. Long lines are split here only at the
# Python-source level (adjacent string literals are concatenated) so the
# emitted CSS line is unchanged but no source line exceeds the line-length cap.
_EDGE_ALIGN_CSS_LINES = (
    ".cms-area--hero, .cms-area--cta,",
    ".cms-widget--header-nav, .cms-widget--footer-nav, .cms-widget--vue,",
    ".cms-breadcrumb {",
    "  max-width: var(--container-max, 1200px) !important;",
    "  width: 100% !important;",
    "  margin-left: auto !important; margin-right: auto !important;",
    "  padding-left: var(--edge-inset) !important;",
    "  padding-right: var(--edge-inset) !important;",
    "  box-sizing: border-box !important;",
    "}",
    # The main content container gets its own fixed, readable gutter instead
    # of var(--edge-inset): on narrow/1200 themes --edge-inset is 0rem, which
    # would otherwise leave body copy with zero horizontal padding.
    ".cms-area--content .container {",
    "  max-width: var(--container-max, 1200px) !important;",
    "  width: 100% !important;",
    "  margin-left: auto !important; margin-right: auto !important;",
    "  padding-left: 1.5rem !important;",
    "  padding-right: 1.5rem !important;",
    "  box-sizing: border-box !important;",
    "}",
    (
        ".cms-widget--header-nav .cms-menu, .cms-widget--footer-nav .cms-menu "
        "{ padding-left: 0 !important; margin-left: 0 !important; }"
    ),
    (
        ".cms-widget--header-nav .cms-menu > .cms-menu__item:first-child > "
        ".cms-menu__link { padding-left: 0 !important; }"
    ),
    ".cms-breadcrumb { gap: 0 !important; padding-left: var(--edge-inset) !important; }",
    (
        ".cms-breadcrumb > a:first-of-type, "
        ".cms-breadcrumb > .cms-breadcrumb__link:first-of-type "
        "{ margin-left: 0 !important; padding-left: 0 !important; }"
    ),
    "@media (max-width: 700px) { :root { --edge-inset: 1rem; } }",
)

EDGE_ALIGN_BLOCK = (
    EDGE_ALIGN_START_MARKER
    + "\n"
    + "\n".join(_EDGE_ALIGN_CSS_LINES)
    + "\n"
    + EDGE_ALIGN_END_MARKER
)

# Matches any prior VBWD_EDGE_ALIGN block (any version) including its markers,
# so a v0/v1 block is replaced wholesale.
_EXISTING_BLOCK_RE = re.compile(
    r"/\* VBWD_EDGE_ALIGN:[^*]*\*/.*?/\* /VBWD_EDGE_ALIGN:[^*]*\*/",
    re.DOTALL,
)


def apply_edge_align(source_css: Optional[str]) -> str:
    """Return ``source_css`` with exactly one canonical EDGE_ALIGN block.

    If a VBWD_EDGE_ALIGN block (any version) already exists, it is replaced
    in place; otherwise the canonical block is appended (with a leading
    newline). Idempotent: ``apply_edge_align(apply_edge_align(x))`` equals
    ``apply_edge_align(x)``. Only the marker block is touched.
    """
    css = source_css or ""
    if _EXISTING_BLOCK_RE.search(css):
        return _EXISTING_BLOCK_RE.sub(lambda _m: EDGE_ALIGN_BLOCK, css, count=1)
    if css == "":
        return EDGE_ALIGN_BLOCK
    separator = "" if css.endswith("\n") else "\n"
    return css + separator + EDGE_ALIGN_BLOCK
