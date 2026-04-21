#!/usr/bin/env python3
"""Generate theme-styles.json — the source of truth for CMS style imports.

Matrix:  6 colour families × 2 widths = 12 themes.

Each theme's source_css is:
    BASE_CSS (shared typography/layout)
  + COLORS[<slug>]  (palette tokens)
  + WIDTHS[<slug>]  (container tokens)

Run:
    python3 docs/imports/_build_theme_styles.py

Output:
    docs/imports/theme-styles.json
"""
from __future__ import annotations

import json
from pathlib import Path
from textwrap import dedent

OUT = Path(__file__).parent / "theme-styles.json"


# ── Shared base (typography + widget primitives) ────────────────────────────

BASE_CSS = dedent("""\
    *, *::before, *::after { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: var(--font-sans, 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif);
      font-size: 16px;
      line-height: 1.65;
      background: var(--color-bg);
      color: var(--color-text);
      -webkit-font-smoothing: antialiased;
    }
    h1, h2, h3, h4, h5, h6 {
      color: var(--color-heading);
      font-family: var(--font-heading, inherit);
      line-height: 1.2;
      letter-spacing: -0.015em;
      margin: 0 0 0.65em;
      font-weight: 700;
    }
    h1 { font-size: clamp(2.2rem, 4vw, 3.25rem); font-weight: 800; }
    h2 { font-size: clamp(1.5rem, 2.4vw, 2rem); margin-top: 0.5em; }
    h3 { font-size: 1.25rem; }
    h4 { font-size: 1.1rem; }
    p  { margin: 0 0 1em; color: var(--color-text); }
    a  {
      color: var(--color-link);
      text-decoration: none;
      font-weight: 600;
      transition: color 0.15s;
    }
    a:hover { color: var(--color-link-hover); text-decoration: underline; text-underline-offset: 3px; }
    img { max-width: 100%; height: auto; display: block; }
    code, kbd, samp {
      font-family: 'JetBrains Mono', ui-monospace, SFMono-Regular, Menlo, monospace;
      background: var(--color-accent-soft);
      color: var(--color-accent-dark);
      padding: 0.15em 0.45em;
      border-radius: 6px;
      font-size: 0.9em;
    }
    blockquote {
      border-left: 4px solid var(--color-accent);
      margin: 1.5em 0;
      padding: 0.6em 1.2em;
      color: var(--color-text-muted);
      background: var(--color-surface-soft);
      border-radius: 0 8px 8px 0;
      font-style: italic;
    }
    blockquote cite { display: block; font-size: 0.85em; font-style: normal; color: var(--color-text-muted); margin-top: 0.5em; }
    ul, ol { margin: 0 0 1em; padding-left: 1.5em; }
    li { margin-bottom: 0.35em; }
    hr { border: 0; border-top: 1px solid var(--color-border); margin: 2.5rem 0; }

    /* Layout */
    .container {
      max-width: var(--container-max);
      width: 100%;
      margin: 0 auto;
      padding: 0 1.5rem;
    }
    section { padding: clamp(3rem, 6vw, 5rem) 0; }
    header {
      background: var(--color-surface);
      border-bottom: 1px solid var(--color-border);
      padding: 0.75rem 0;
    }
    nav a { color: var(--color-text); font-weight: 500; padding: 0 0.875rem; }
    nav a:hover { color: var(--color-accent); text-decoration: none; }
    footer {
      background: var(--color-surface-soft);
      border-top: 1px solid var(--color-border);
      padding: 2.5rem 0;
      color: var(--color-text-muted);
      font-size: 0.9rem;
    }

    /* Buttons — 4 variants, always contrast-safe */
    .btn {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 0.5rem;
      padding: 0.7rem 1.4rem;
      border-radius: 8px;
      font-weight: 600;
      font-size: 0.95rem;
      cursor: pointer;
      border: 2px solid var(--color-border);
      background: var(--color-surface);
      color: var(--color-text);
      text-decoration: none;
      transition: background 0.15s, border-color 0.15s, color 0.15s, transform 0.05s;
      line-height: 1.2;
    }
    .btn:hover { background: var(--color-surface-soft); border-color: var(--color-text-muted); text-decoration: none; }
    .btn:active { transform: translateY(1px); }
    .btn--accent {
      background: var(--color-accent);
      color: var(--color-accent-fg);
      border-color: var(--color-accent);
    }
    .btn--accent:hover { background: var(--color-accent-dark); border-color: var(--color-accent-dark); color: var(--color-accent-fg); }
    .btn--contrast {
      background: var(--color-contrast-bg);
      color: var(--color-contrast-fg);
      border-color: var(--color-contrast-bg);
    }
    .btn--contrast:hover { background: var(--color-contrast-hover-bg); border-color: var(--color-contrast-hover-bg); color: var(--color-contrast-fg); }
    .btn[disabled], .btn.is-disabled {
      opacity: 0.5;
      cursor: not-allowed;
      pointer-events: none;
    }

    /* Cards + feature grid */
    .card {
      background: var(--color-surface);
      border: 1px solid var(--color-border);
      border-radius: 14px;
      padding: 1.5rem;
      box-shadow: 0 1px 2px rgba(0,0,0,0.04);
    }
    .cards-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
      gap: 1.25rem;
    }

    /* Hero */
    .hero {
      background: var(--color-gradient, var(--color-accent));
      color: var(--color-accent-fg, #fff);
      padding: clamp(3.5rem, 8vw, 6rem) 1.5rem;
      text-align: center;
      border-radius: 22px;
      margin: 1rem auto 3rem;
      max-width: var(--container-max);
      position: relative;
      overflow: hidden;
    }
    .hero h1, .hero h2 { color: inherit; }
    .hero__eyebrow {
      display: inline-block;
      padding: 0.35rem 0.9rem;
      border-radius: 999px;
      background: rgba(255,255,255,0.18);
      color: #fff;
      font-size: 0.78rem;
      font-weight: 700;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      margin-bottom: 1.25rem;
    }
    .hero__subtitle {
      max-width: 720px;
      margin: 0 auto 1.75rem;
      font-size: 1.15rem;
      opacity: 0.92;
    }
    .hero__ctas { display: inline-flex; gap: 0.75rem; flex-wrap: wrap; justify-content: center; }

    /* CTA band */
    .cta-band {
      background: var(--color-gradient, var(--color-accent));
      color: var(--color-accent-fg, #fff);
      padding: clamp(2.5rem, 5vw, 4rem) 1.5rem;
      text-align: center;
      border-radius: 18px;
      margin: 3rem auto;
      max-width: var(--container-max);
    }
    .cta-band h2, .cta-band p { color: inherit; }

    /* Columns (2 / 3) */
    .cols-2, .cols-3 { display: grid; gap: 1.5rem; }
    .cols-2 { grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); }
    .cols-3 { grid-template-columns: repeat(auto-fit, minmax(240px, 1fr)); }

    /* Carousel (CSS-only scroll-snap) */
    .carousel {
      display: flex;
      gap: 1rem;
      overflow-x: auto;
      scroll-snap-type: x mandatory;
      padding-bottom: 1rem;
      margin: 1.5rem 0;
    }
    .carousel > * {
      flex: 0 0 clamp(240px, 35vw, 320px);
      scroll-snap-align: start;
    }

    /* Testimonial / pull quote */
    .testimonial {
      text-align: center;
      max-width: 780px;
      margin: 2.5rem auto;
      padding: 2rem 1.5rem;
      border-top: 1px solid var(--color-border);
      border-bottom: 1px solid var(--color-border);
    }
    .testimonial p { font-size: 1.15rem; font-style: italic; color: var(--color-text); }
    .testimonial cite { display: block; margin-top: 1rem; font-size: 0.9rem; color: var(--color-text-muted); font-style: normal; }

    /* Pricing / plan row */
    .plans { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 1.25rem; }
    .plan { background: var(--color-surface); border: 1px solid var(--color-border); border-radius: 14px; padding: 1.75rem; }
    .plan--highlight { border-color: var(--color-accent); box-shadow: 0 0 0 3px var(--color-accent-soft); }
    .plan__price { font-size: 2.25rem; font-weight: 800; color: var(--color-heading); margin: 0.5rem 0 1rem; }
    .plan ul { list-style: none; padding: 0; margin: 0 0 1.5rem; }
    .plan li { padding: 0.4rem 0; border-bottom: 1px solid var(--color-border); }
    .plan li:last-child { border-bottom: 0; }

    /* Responsive tweaks */
    @media (max-width: 640px) {
      h1 { font-size: 2rem; }
      h2 { font-size: 1.4rem; }
      .container { padding: 0 1rem; }
      .hero { margin-left: 0.5rem; margin-right: 0.5rem; border-radius: 14px; }
      .cta-band { border-radius: 12px; margin-left: 0.5rem; margin-right: 0.5rem; }
    }
""")


# ── Colour palettes ─────────────────────────────────────────────────────────

def tokens(**kv):
    lines = ["/* palette */", ":root {"]
    for k, v in kv.items():
        lines.append(f"  --{k}: {v};")
    lines.append("}")
    return "\n".join(lines) + "\n"


COLORS = {
    "light-clean": {
        "name": "Light — Clean",
        "tokens": dict(
            **{"color-accent": "#2563eb", "color-accent-soft": "#dbeafe",
               "color-accent-dark": "#1d4ed8", "color-accent-fg": "#ffffff",
               "color-contrast-bg": "#0f172a", "color-contrast-fg": "#f8fafc",
               "color-contrast-hover-bg": "#1e293b",
               "color-link": "#1d4ed8", "color-link-hover": "#1e40af",
               "color-bg": "#ffffff", "color-surface": "#ffffff",
               "color-surface-soft": "#f8fafc", "color-border": "#e2e8f0",
               "color-text": "#0f172a", "color-text-muted": "#475569",
               "color-heading": "#0b1220",
               "color-gradient": "linear-gradient(135deg, #2563eb 0%, #7c3aed 100%)"}
        ),
    },
    "light-warm": {
        "name": "Light — Warm",
        "tokens": dict(
            **{"color-accent": "#d97706", "color-accent-soft": "#fef3c7",
               "color-accent-dark": "#b45309", "color-accent-fg": "#ffffff",
               "color-contrast-bg": "#1c1917", "color-contrast-fg": "#fafaf9",
               "color-contrast-hover-bg": "#292524",
               "color-link": "#b45309", "color-link-hover": "#92400e",
               "color-bg": "#fffbf5", "color-surface": "#ffffff",
               "color-surface-soft": "#fef8ef", "color-border": "#f1e9db",
               "color-text": "#1c1917", "color-text-muted": "#78716c",
               "color-heading": "#1c1210",
               "color-gradient": "linear-gradient(135deg, #d97706 0%, #dc2626 100%)"}
        ),
    },
    "light-cool": {
        "name": "Light — Cool",
        "tokens": dict(
            **{"color-accent": "#0891b2", "color-accent-soft": "#cffafe",
               "color-accent-dark": "#0e7490", "color-accent-fg": "#ffffff",
               "color-contrast-bg": "#0c4a6e", "color-contrast-fg": "#f0f9ff",
               "color-contrast-hover-bg": "#075985",
               "color-link": "#0e7490", "color-link-hover": "#155e75",
               "color-bg": "#f8fafc", "color-surface": "#ffffff",
               "color-surface-soft": "#f1f5f9", "color-border": "#dbe4ec",
               "color-text": "#0f172a", "color-text-muted": "#475569",
               "color-heading": "#0c1929",
               "color-gradient": "linear-gradient(135deg, #0891b2 0%, #2563eb 100%)"}
        ),
    },
    "dark-ocean": {
        "name": "Dark — Ocean",
        "tokens": dict(
            **{"color-accent": "#22d3ee", "color-accent-soft": "#0e7490",
               "color-accent-dark": "#06b6d4", "color-accent-fg": "#021c2a",
               "color-contrast-bg": "#f0f9ff", "color-contrast-fg": "#021c2a",
               "color-contrast-hover-bg": "#e0f2fe",
               "color-link": "#67e8f9", "color-link-hover": "#a5f3fc",
               "color-bg": "#031625", "color-surface": "#0a2540",
               "color-surface-soft": "#0f2e4d", "color-border": "#164160",
               "color-text": "#e2e8f0", "color-text-muted": "#94a3b8",
               "color-heading": "#f1f5f9",
               "color-gradient": "linear-gradient(135deg, #0ea5e9 0%, #06b6d4 100%)"}
        ),
    },
    "dark-forest": {
        "name": "Dark — Forest",
        "tokens": dict(
            **{"color-accent": "#34d399", "color-accent-soft": "#065f46",
               "color-accent-dark": "#10b981", "color-accent-fg": "#022c1a",
               "color-contrast-bg": "#ecfdf5", "color-contrast-fg": "#022c1a",
               "color-contrast-hover-bg": "#d1fae5",
               "color-link": "#6ee7b7", "color-link-hover": "#a7f3d0",
               "color-bg": "#0a1f17", "color-surface": "#0f2e22",
               "color-surface-soft": "#143a2b", "color-border": "#1e513c",
               "color-text": "#e6ede8", "color-text-muted": "#8ea89a",
               "color-heading": "#f0f4f1",
               "color-gradient": "linear-gradient(135deg, #10b981 0%, #14b8a6 100%)"}
        ),
    },
    "dark-purple": {
        "name": "Dark — Purple",
        "tokens": dict(
            **{"color-accent": "#c084fc", "color-accent-soft": "#6b21a8",
               "color-accent-dark": "#a855f7", "color-accent-fg": "#1a0a2e",
               "color-contrast-bg": "#faf5ff", "color-contrast-fg": "#1a0a2e",
               "color-contrast-hover-bg": "#f3e8ff",
               "color-link": "#d8b4fe", "color-link-hover": "#e9d5ff",
               "color-bg": "#120726", "color-surface": "#1e1038",
               "color-surface-soft": "#27174a", "color-border": "#3f2766",
               "color-text": "#e9e4f2", "color-text-muted": "#a196b9",
               "color-heading": "#f3ecff",
               "color-gradient": "linear-gradient(135deg, #a855f7 0%, #ec4899 100%)"}
        ),
    },
}


# ── Widths ───────────────────────────────────────────────────────────────────

WIDTHS = {
    "narrow":    {"label": "Narrow",     "max": "1100px", "sort_offset": 0},
    "fullwidth": {"label": "Full-width", "max": "100%",   "sort_offset": 1},
}


# ── Emit ─────────────────────────────────────────────────────────────────────

def build_one(color_slug: str, color: dict, width_slug: str, width: dict, sort_order: int) -> dict:
    slug = f"{color_slug}-{width_slug}"
    width_tokens = (
        "/* width */\n:root {\n"
        f"  --container-max: {width['max']};\n"
        "}\n"
    )
    source_css = (
        BASE_CSS
        + "\n"
        + tokens(**color["tokens"])
        + "\n"
        + width_tokens
    )
    return {
        "slug": slug,
        "name": f"{color['name']} — {width['label']}",
        "source_css": source_css,
        "sort_order": sort_order,
        "is_active": True,
        "is_default": slug == "light-clean-narrow",
    }


def main() -> None:
    themes: list[dict] = []
    order = 0
    for color_slug, color in COLORS.items():
        for width_slug, width in WIDTHS.items():
            order += 1
            themes.append(build_one(color_slug, color, width_slug, width, sort_order=order))

    obj = {
        "version": 1,
        "description": "CMS style import — 6 colours × 2 widths (sprint 27 theme matrix).",
        "default_slug": "light-clean-narrow",
        "themes": themes,
    }
    OUT.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n")
    print(f"Wrote {len(themes)} themes → {OUT}")


if __name__ == "__main__":
    main()
