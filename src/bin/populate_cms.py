#!/usr/bin/env python3
"""
Populate the CMS database with demo data.

Creates:
  - All themes from docs/imports/theme-styles.json (CmsStyle)
  - Navigation widgets: header-nav (menu with Pricing submenu), footer-nav (menu)
  - Content widgets: hero-home1, hero-home2, cta-primary, features-3col, features-slideshow,
                     pricing-embed-demo, pricing-native-plans, contact-form (vue-component) (html)
  - 8 layouts: contact-form, ghrm-software-catalogue, ghrm-software-detail,
               home-v1, home-v2, landing, content-page, native-pricing-page
  - 19 pages: index (the canonical homepage rendered at /), home2, landing2,
               landing3, about, privacy, terms, contact,
               features, pricing-embedded, pricing-native, we-are-launching-soon,
               ghrm-software-catalogue, ghrm-software-detail, software, category,
               category/backend, category/fe-user, category/fe-admin

Header nav: Home | Features | Pricing (submenu: Embedded / Native / All Plans) | About | Software

All inserts are idempotent — existing slugs are updated, menu items are always replaced.

Usage:
    python /app/plugins/cms/src/bin/populate_cms.py
"""
import sys
import re
import base64
import json as _json
from pathlib import Path
from pathlib import Path as _Path
from typing import Optional, cast

project_root = Path(__file__).parent.parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from vbwd.extensions import db  # noqa: E402
from plugins.cms.src.models.cms_style import CmsStyle  # noqa: E402
from plugins.cms.src.models.cms_widget import CmsWidget  # noqa: E402
from plugins.cms.src.models.cms_menu_item import CmsMenuItem  # noqa: E402
from plugins.cms.src.models.cms_layout import CmsLayout  # noqa: E402
from plugins.cms.src.models.cms_layout_widget import CmsLayoutWidget  # noqa: E402
from plugins.cms.src.models.cms_routing_rule import CmsRoutingRule  # noqa: E402
from plugins.cms.src.bin.apply_style_alignment import (  # noqa: E402
    apply_alignment_to_all_styles,
)


# ─── Helpers ──────────────────────────────────────────────────────────────────


def _split_widget_content(html: str) -> tuple:
    """Extract <style> blocks → CSS; base64-encode the remaining HTML.

    Returns (content_json_dict, source_css_str).
    content_json = {"content": "<base64 of html without inline styles>"}
    """
    css_parts: list = []

    def _grab(m):
        css_parts.append(m.group(1).strip())
        return ""

    html_clean = re.sub(
        r"<style[^>]*>(.*?)</style>", _grab, html, flags=re.DOTALL
    ).strip()
    b64 = base64.b64encode(html_clean.encode("utf-8")).decode("ascii")
    return {"content": b64}, "\n\n".join(css_parts)


# ─── Styles ───────────────────────────────────────────────────────────────────

# Themes are authored as data in docs/imports/theme-styles.json.
# Re-regenerate via docs/imports/_build_theme_styles.py.
_THEMES_PATH = (
    _Path(__file__).resolve().parents[2] / "docs" / "imports" / "theme-styles.json"
)


def _unwrap_envelope(doc: dict, entity_key: str) -> list[dict]:
    """Return the rows of an S46 export envelope (``{"vbwd_export": <key>,
    "version": N, "<key>": [rows]}``), tolerating an already-bare list/dict.

    The demo import files are S46 envelopes; the seeder reads them directly
    (it does not go through the import service), so it unwraps here. DRY: one
    home for the unwrap used by every loader below.
    """
    if isinstance(doc, dict) and entity_key in doc:
        rows = doc.get(entity_key)
        return rows if isinstance(rows, list) else []
    if isinstance(doc, list):
        return doc
    return []


def _load_theme_styles() -> tuple[list[dict], str | None]:
    if not _THEMES_PATH.exists():
        print(
            f"  WARN: theme-styles.json missing at {_THEMES_PATH} — no styles imported"
        )
        return [], None
    doc = _json.loads(_THEMES_PATH.read_text())
    # S46 envelope: rows live under "cms_styles" (legacy bare shape used "themes").
    rows = _unwrap_envelope(doc, "cms_styles") or doc.get("themes", [])
    return rows, doc.get("default_slug")


STYLES, DEFAULT_STYLE_SLUG = _load_theme_styles()

LEGACY_STYLE_SLUGS = [
    "light-clean",
    "light-warm",
    "light-cool",
    "light-soft",
    "light-paper",
    "dark-midnight",
    "dark-charcoal",
    "dark-forest",
    "dark-purple",
    "dark-carbon",
]


# ─── Widget content ────────────────────────────────────────────────────────────

HERO_HOME1_HTML = """
<section class="hero">
  <div class="container">
    <h1>Build Something Amazing</h1>
    <p class="hero-sub">The modern platform for teams who ship fast. Scalable, secure, and developer-friendly.</p>
    <div class="hero-cta">
      <a href="/signup" class="btn btn-primary">Get Started Free</a>
      <a href="/demo" class="btn btn-outline" style="margin-left:1rem">Watch Demo</a>
    </div>
  </div>
</section>
<style>
.hero { padding: 6rem 0; text-align: center; }
.hero h1 { font-size: clamp(2rem, 5vw, 3.5rem); margin-bottom: 1rem; }
.hero-sub { font-size: 1.25rem; opacity: 0.75; max-width: 600px; margin: 0 auto 2.5rem; }
.hero-cta { display: flex; justify-content: center; flex-wrap: wrap; gap: 0.75rem; }
</style>
"""

HERO_HOME2_HTML = """
<section class="hero-split">
  <div class="container">
    <div class="hero-split__text">
      <span class="badge">New in 2026</span>
      <h1>Smarter Workflows, Faster Results</h1>
      <p>From idea to production in minutes. Automate your processes and focus on what matters most — your product.</p>
      <a href="/start" class="btn btn-primary">Start Building</a>
    </div>
    <div class="hero-split__image">
      <div class="hero-placeholder">🚀</div>
    </div>
  </div>
</section>
<style>
.hero-split { padding: 5rem 0; }
.hero-split .container { display: grid; grid-template-columns: 1fr 1fr; gap: 3rem; align-items: center; }
@media (max-width: 768px) { .hero-split .container { grid-template-columns: 1fr; } }
.badge { display: inline-block; padding: 2px 10px; border-radius: 12px; background: var(--color-primary); color: #fff; font-size: 0.8rem; font-weight: 600; margin-bottom: 1rem; }  # noqa: E501
.hero-split h1 { font-size: clamp(1.75rem, 3.5vw, 3rem); margin-bottom: 1rem; }
.hero-split p { font-size: 1.1rem; opacity: 0.8; margin-bottom: 2rem; }
.hero-placeholder { font-size: 8rem; text-align: center; line-height: 1; background: var(--color-surface, #f8fafc); border-radius: 16px; padding: 3rem; }  # noqa: E501
</style>
"""

CTA_PRIMARY_HTML = """
<section class="cta-section">
  <div class="container">
    <h2>Ready to get started?</h2>
    <p>Join thousands of teams already using our platform. No credit card required.</p>
    <a href="/signup" class="btn btn-primary">Start Free Trial</a>
  </div>
</section>
<style>
.cta-section { text-align: center; padding: 5rem 0; background: var(--color-surface, #f8fafc); }
.cta-section h2 { font-size: 2rem; margin-bottom: 0.75rem; }
.cta-section p { opacity: 0.75; margin-bottom: 2rem; font-size: 1.1rem; }
</style>
"""

FEATURES_3COL_HTML: str = """
<section class="features">
  <div class="container">
    <h2 class="features__title">Why teams choose us</h2>
    <div class="features__grid">
      <div class="feature-card">
        <div class="feature-icon">⚡</div>
        <h3>Lightning Fast</h3>
        <p>Sub-second response times with global CDN and edge caching built in from day one.</p>
      </div>
      <div class="feature-card">
        <div class="feature-icon">🔒</div>
        <h3>Enterprise Security</h3>
        <p>SOC 2 Type II certified. End-to-end encryption, audit logs, and fine-grained permissions.</p>
      </div>
      <div class="feature-card">
        <div class="feature-icon">🔌</div>
        <h3>API-First</h3>
        <p>REST and GraphQL APIs, webhooks, and 200+ native integrations. Works with your stack.</p>
      </div>
    </div>
  </div>
</section>
<style>
.features { padding: 5rem 0; }
.features__title { text-align: center; font-size: 2rem; margin-bottom: 3rem; }
.features__grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 2rem; }
.feature-card { padding: 2rem; border-radius: 12px; background: var(--color-surface, #f8fafc); border: 1px solid var(--color-border, #e2e8f0); }  # noqa: E501
.feature-icon { font-size: 2.5rem; margin-bottom: 1rem; }
.feature-card h3 { font-size: 1.2rem; margin-bottom: 0.5rem; }
.feature-card p { opacity: 0.75; font-size: 0.95rem; }
</style>
"""

PRICING_2COL_HTML = """
<section class="pricing">
  <div class="container">
    <h2 class="pricing__title">Simple, Transparent Pricing</h2>
    <div class="pricing__grid">
      <div class="pricing-card">
        <div class="pricing-card__tier">Starter</div>
        <div class="pricing-card__price">$0<span>/mo</span></div>
        <ul class="pricing-card__features">
          <li>✓ 3 projects</li><li>✓ 5 GB storage</li>
          <li>✓ Community support</li><li>✓ Basic analytics</li>
        </ul>
        <a href="/signup" class="btn btn-outline" style="width:100%;justify-content:center">Get Started</a>
      </div>
      <div class="pricing-card pricing-card--featured">
        <div class="pricing-card__tier">Pro</div>
        <div class="pricing-card__price">$49<span>/mo</span></div>
        <ul class="pricing-card__features">
          <li>✓ Unlimited projects</li><li>✓ 100 GB storage</li>
          <li>✓ Priority support</li><li>✓ Advanced analytics</li>
          <li>✓ Custom domains</li><li>✓ Team collaboration</li>
        </ul>
        <a href="/signup?plan=pro" class="btn btn-primary" style="width:100%;justify-content:center">Start Free Trial</a>  # noqa: E501
      </div>
    </div>
  </div>
</section>
<style>
.pricing { padding: 5rem 0; }
.pricing__title { text-align: center; font-size: 2rem; margin-bottom: 3rem; }
.pricing__grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 2rem; max-width: 720px; margin: 0 auto; }  # noqa: E501
.pricing-card { padding: 2.5rem; border-radius: 12px; background: var(--color-surface, #f8fafc); border: 1px solid var(--color-border, #e2e8f0); }  # noqa: E501
.pricing-card--featured { border-color: var(--color-primary, #2563eb); box-shadow: 0 0 0 2px var(--color-primary, #2563eb); }  # noqa: E501
.pricing-card__tier { font-size: 0.85rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.1em; opacity: 0.7; margin-bottom: 0.5rem; }  # noqa: E501
.pricing-card__price { font-size: 2.5rem; font-weight: 800; margin-bottom: 1.5rem; }
.pricing-card__price span { font-size: 1rem; font-weight: 400; opacity: 0.6; }
.pricing-card__features { list-style: none; padding: 0; margin: 0 0 2rem; }
.pricing-card__features li { padding: 0.35rem 0; font-size: 0.95rem; }
</style>
"""

TARIF_PLANS_ROOT_HTML = """
<div id="vbwd-iframe-root"></div>
<script
  src="/embed/widget.js"
  data-embed="landing1"
  data-category="root"
  data-container="vbwd-iframe-root"
  data-locale="en"
  data-theme="light"
  data-height="700"
></script>
"""

TARIF_PLANS_BACKEND_HTML = """
<div id="vbwd-iframe-backend"></div>
<script
  src="/embed/widget.js"
  data-embed="landing1"
  data-category="backend"
  data-container="vbwd-iframe-backend"
  data-locale="en"
  data-theme="light"
  data-height="700"
></script>
"""

# ─── Features slideshow ────────────────────────────────────────────────────────

FEATURES_SLIDESHOW_HTML = """
<section class="features-hero">
  <div class="container">
    <h1>VBWD Platform Features</h1>
    <p class="features-hero__sub">Everything you need to build, launch, and scale a SaaS product — without months of boilerplate.</p>  # noqa: E501
  </div>
</section>

<section class="features-slideshow">
  <div class="container">
    <div class="slideshow" id="vbwd-slideshow">
      <div class="slide slide--active">
        <div class="slide__icon">💳</div>
        <h2>Subscription Billing</h2>
        <p>Stripe, PayPal, and YooKassa out of the box. Monthly, annual, and usage-based plans. Automated invoicing and dunning sequences.</p>  # noqa: E501
      </div>
      <div class="slide">
        <div class="slide__icon">👥</div>
        <h2>User Management</h2>
        <p>Registration, login, roles, profiles, and invitations. JWT-based authentication with refresh tokens and session management.</p>  # noqa: E501
      </div>
      <div class="slide">
        <div class="slide__icon">🧩</div>
        <h2>Plugin System</h2>
        <p>Extend without touching core. Frontend and backend plugins with lifecycle hooks, dependency resolution, and hot registration.</p>  # noqa: E501
      </div>
      <div class="slide">
        <div class="slide__icon">📄</div>
        <h2>CMS &amp; Pages</h2>
        <p>Manage layouts, widgets, menus, styles, and content pages from the admin panel. No code changes required for content updates.</p>  # noqa: E501
      </div>
      <div class="slide">
        <div class="slide__icon">📦</div>
        <h2>Software Catalogue (GHRM)</h2>
        <p>Subscription-gated access to GitHub repositories. Deploy tokens, collaborator management, and automatic version tracking.</p>  # noqa: E501
      </div>
      <div class="slide">
        <div class="slide__icon">🔌</div>
        <h2>Embeddable Pricing</h2>
        <p>Drop a &lt;script&gt; tag on any page. A responsive pricing table renders inside a sandboxed iframe. Zero framework dependency.</p>  # noqa: E501
      </div>
    </div>

    <div class="slideshow-controls">
      <button class="slide-btn slide-btn--prev" onclick="vbwdSlidePrev()">&#8249;</button>
      <div class="slide-dots" id="vbwd-slide-dots"></div>
      <button class="slide-btn slide-btn--next" onclick="vbwdSlideNext()">&#8250;</button>
    </div>
  </div>
</section>

<section class="features-docs-link">
  <div class="container">
    <p>
      Full documentation &rarr;
      <a href="https://github.com/dantweb/vbwd-sdk/blob/main/docs/features.md" target="_blank" rel="noopener">
        docs/features.md on GitHub &#8599;
      </a>
    </p>
  </div>
</section>

<script>
(function () {
  var current = 0;
  var slides = document.querySelectorAll('#vbwd-slideshow .slide');
  var dotsContainer = document.getElementById('vbwd-slide-dots');
  slides.forEach(function (_, i) {
    var dot = document.createElement('button');
    dot.className = 'slide-dot' + (i === 0 ? ' slide-dot--active' : '');
    dot.setAttribute('aria-label', 'Slide ' + (i + 1));
    dot.onclick = function () { goTo(i); };
    dotsContainer.appendChild(dot);
  });
  function goTo(n) {
    slides[current].classList.remove('slide--active');
    dotsContainer.children[current].classList.remove('slide-dot--active');
    current = (n + slides.length) % slides.length;
    slides[current].classList.add('slide--active');
    dotsContainer.children[current].classList.add('slide-dot--active');
  }
  window.vbwdSlidePrev = function () { goTo(current - 1); };
  window.vbwdSlideNext = function () { goTo(current + 1); };
  setInterval(function () { goTo(current + 1); }, 5000);
}());
</script>

<style>
.features-hero { padding: 4rem 0 2rem; text-align: center; }
.features-hero h1 { font-size: clamp(1.75rem, 4vw, 2.75rem); margin-bottom: 0.75rem; }
.features-hero__sub { font-size: 1.1rem; opacity: 0.75; max-width: 540px; margin: 0 auto; }
.features-slideshow { padding: 3rem 0 4rem; }
.slideshow { position: relative; }
.slide { display: none; text-align: center; padding: 2.5rem 2rem; background: var(--color-surface, #f8fafc); border-radius: 16px; border: 1px solid var(--color-border, #e2e8f0); animation: vbwdFadeIn 0.4s ease; }  # noqa: E501
.slide--active { display: block; }
@keyframes vbwdFadeIn { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: none; } }
.slide__icon { font-size: 3rem; margin-bottom: 1rem; }
.slide h2 { font-size: 1.5rem; margin-bottom: 0.75rem; }
.slide p { opacity: 0.8; font-size: 1rem; max-width: 520px; margin: 0 auto; }
.slideshow-controls { display: flex; align-items: center; justify-content: center; gap: 1rem; margin-top: 1.5rem; }
.slide-btn { background: none; border: 2px solid var(--color-border, #e2e8f0); border-radius: 50%; width: 40px; height: 40px; font-size: 1.4rem; cursor: pointer; color: var(--color-text, #1e293b); transition: all 0.15s; line-height: 1; }  # noqa: E501
.slide-btn:hover { border-color: var(--color-primary, #2563eb); color: var(--color-primary, #2563eb); }
.slide-dots { display: flex; gap: 6px; }
.slide-dot { width: 8px; height: 8px; border-radius: 50%; border: none; background: var(--color-border, #e2e8f0); cursor: pointer; padding: 0; transition: background 0.2s; }  # noqa: E501
.slide-dot--active { background: var(--color-primary, #2563eb); }
.features-docs-link { text-align: center; padding: 1rem 0 3rem; }
.features-docs-link p { opacity: 0.75; }
.features-docs-link a { color: var(--color-primary, #2563eb); font-weight: 600; }
</style>
"""

# Shared feature bullets rendered on EVERY pricing card (Landing1View renders one
# shared list, not per-plan). Kept comma-free: the embed forwards this list as a
# single comma-separated attribute, so a comma inside a bullet would split it.
# Defined here (above the embed guide) so the live embed script tag and the
# native-plans config can both reference the SAME list — they can never drift.
NATIVE_PRICING_FEATURES = [
    "All core platform features",
    "Unlimited projects",
    "Priority email support",
    "Cancel anytime",
]

# ─── Embedded pricing guide ────────────────────────────────────────────────────

PRICING_EMBED_GUIDE_HTML = """
<section class="embed-hero">
  <div class="container">
    <h1>Embedded Pricing</h1>
    <p class="embed-hero__sub">Add a fully hosted, responsive pricing table to any page with a single &lt;script&gt; tag. No React, no Vue, no build step required.</p>  # noqa: E501
  </div>
</section>

<section class="embed-guide">
  <div class="container">

    <h2>Live Example</h2>
    <p class="embed-live-label">This is the embedded widget running live on this page:</p>
    <div id="embed-live-preview" class="embed-live-wrap"></div>
    <script
      src="/embed/widget.js"
      data-embed="landing1"
      data-category="root"
      data-container="embed-live-preview"
      data-locale="en"
      data-theme="indigo"
      data-highlight="pro"
      data-features="__EMBED_LIVE_FEATURES__"
      data-height="650"
    ></script>

    <h2>How It Works</h2>
    <ol class="embed-steps">
      <li>
        <strong>1 — Add a container div</strong>
        <pre><code>&lt;div id="pricing-root"&gt;&lt;/div&gt;</code></pre>
      </li>
      <li>
        <strong>2 — Load the widget script</strong>
        <pre><code>&lt;script
  src="https://your-vbwd-instance.com/embed/widget.js"
  data-embed="landing1"
  data-category="root"
  data-container="pricing-root"
  data-locale="en"
  data-theme="indigo"
  data-height="700"
  data-highlight="pro"
  data-features="All core platform features,Unlimited projects,Priority email support,Cancel anytime"
&gt;&lt;/script&gt;</code></pre>
      </li>
      <li>
        <strong>3 — Done.</strong> The widget renders inside a sandboxed iframe. Billing, checkout, and plan management are fully handled by your VBWD backend.  # noqa: E501
      </li>
    </ol>

    <h2>Configuration Attributes</h2>
    <table class="embed-table">
      <thead>
        <tr><th>Attribute</th><th>Required</th><th>Default</th><th>Description</th></tr>
      </thead>
      <tbody>
        <tr><td><code>data-embed</code></td><td>Yes</td><td>—</td><td>Widget preset. Use <code>landing1</code> for the standard pricing table.</td></tr>  # noqa: E501
        <tr><td><code>data-category</code></td><td>No</td><td><code>root</code></td><td>Tariff plan category slug. <code>root</code> shows all plans.</td></tr>  # noqa: E501
        <tr><td><code>data-container</code></td><td>Yes</td><td>—</td><td>ID of the host <code>&lt;div&gt;</code>.</td></tr>  # noqa: E501
        <tr><td><code>data-locale</code></td><td>No</td><td><code>en</code></td><td>UI language: <code>en</code>, <code>ru</code>, <code>fr</code>, <code>de</code>, …</td></tr>  # noqa: E501
        <tr><td><code>data-theme</code></td><td>No</td><td><code>default</code></td><td>Card colour theme: <code>default</code>, <code>light</code>, <code>dark</code>, <code>teal</code>, <code>indigo</code>, <code>emerald</code>. Any other value falls back to <code>default</code>.</td></tr>  # noqa: E501
        <tr><td><code>data-height</code></td><td>No</td><td><code>700</code></td><td>iframe height in pixels.</td></tr>
        <tr><td><code>data-highlight</code></td><td>No</td><td>—</td><td>Plan slug rendered as featured.</td></tr>
        <tr><td><code>data-image</code></td><td>No</td><td>—</td><td>Header image URL for the card.</td></tr>
        <tr><td><code>data-features</code></td><td>No</td><td>—</td><td>Comma-separated feature bullets.</td></tr>
        <tr><td><code>data-heading</code></td><td>No</td><td>—</td><td>Overrides the card heading.</td></tr>
        <tr><td><code>data-subtitle</code></td><td>No</td><td>—</td><td>Overrides the card subtitle.</td></tr>
        <tr><td><code>data-cta</code></td><td>No</td><td>—</td><td>Overrides the CTA button label.</td></tr>
        <tr><td><code>data-badge</code></td><td>No</td><td>—</td><td>Overrides the featured-plan badge.</td></tr>
      </tbody>
    </table>

    <p class="embed-note"><code>data-features</code> is one comma-separated list, so a single
      feature must not contain a comma. Leave <code>data-heading</code>, <code>data-subtitle</code>,
      <code>data-cta</code> and <code>data-badge</code> unset to use the built-in localised text.</p>

    <h2>Show a Specific Category</h2>
    <pre><code>&lt;script
  src="/embed/widget.js"
  data-embed="landing1"
  data-category="backend"
  data-container="pricing-root"
  data-theme="dark"
&gt;&lt;/script&gt;</code></pre>

    <h2>Customise Copy, Theme &amp; Highlight</h2>
    <pre><code>&lt;script
  src="/embed/widget.js"
  data-embed="landing1"
  data-category="root"
  data-container="pricing-root"
  data-theme="emerald"
  data-highlight="pro"
  data-badge="Most popular"
  data-heading="Choose your plan"
  data-subtitle="Upgrade or downgrade anytime"
  data-cta="Get started"
  data-features="All core platform features,Unlimited projects,Cancel anytime"
&gt;&lt;/script&gt;</code></pre>

  </div>
</section>

<style>
.embed-hero { padding: 4rem 0 2rem; text-align: center; }
.embed-hero h1 { font-size: clamp(1.75rem, 4vw, 2.75rem); margin-bottom: 0.75rem; }
.embed-hero__sub { font-size: 1.1rem; opacity: 0.75; max-width: 600px; margin: 0 auto; }
.embed-guide { padding: 3rem 0 5rem; }
.embed-guide h2 { font-size: 1.4rem; margin: 2.5rem 0 1rem; padding-bottom: 0.5rem; border-bottom: 2px solid var(--color-border, #e2e8f0); }  # noqa: E501
.embed-steps { padding-left: 0; list-style: none; }
.embed-steps li { margin-bottom: 2rem; }
.embed-steps strong { display: block; margin-bottom: 0.5rem; font-size: 1rem; }
pre { background: var(--color-surface, #f8fafc); border: 1px solid var(--color-border, #e2e8f0); border-radius: 8px; padding: 1rem 1.25rem; overflow-x: auto; margin: 0.5rem 0 1rem; }  # noqa: E501
code { font-family: 'JetBrains Mono', 'Fira Code', 'Courier New', monospace; font-size: 0.875rem; }
.embed-table { width: 100%; border-collapse: collapse; margin: 1rem 0 2rem; font-size: 0.875rem; }
.embed-table th { background: var(--color-surface, #f8fafc); padding: 0.6rem 0.875rem; text-align: left; border: 1px solid var(--color-border, #e2e8f0); font-weight: 600; }  # noqa: E501
.embed-table td { padding: 0.6rem 0.875rem; border: 1px solid var(--color-border, #e2e8f0); vertical-align: top; }
.embed-table td code, .embed-table th code { background: var(--color-surface, #f8fafc); padding: 2px 5px; border-radius: 3px; font-size: 0.8rem; border: 1px solid var(--color-border, #e2e8f0); }  # noqa: E501
.embed-live-label { color: var(--color-muted, #64748b); font-size: 0.9rem; margin-bottom: 1rem; }
.embed-live-wrap { border: 2px dashed var(--color-border, #e2e8f0); border-radius: 12px; padding: 1rem; margin-bottom: 2.5rem; min-height: 100px; }  # noqa: E501
</style>
"""

# Resolve the live embed script's feature list from the single source of truth so
# the seeded guide and the native-plans card advertise the exact same bullets.
PRICING_EMBED_GUIDE_HTML = PRICING_EMBED_GUIDE_HTML.replace(
    "__EMBED_LIVE_FEATURES__", ",".join(NATIVE_PRICING_FEATURES)
)

# ─── Native pricing Vue component widget config ────────────────────────────────
# Stored in CmsWidget.config; the frontend "vue-component" widget type reads this
# to determine which Vue component to render and with which props.

NATIVE_PRICING_CSS = """\
/* ============================================================
   NativePricingPlans widget CSS
   Three ready-to-use styles. Uncomment ONE block at a time.
   The active block overrides the theme-switcher preset colors.
   ============================================================ */

/* ── STYLE 1 (default): Theme-aware ──────────────────────────
   No overrides. Plan cards automatically follow the active
   theme-switcher preset (light / dark / forest / ocean …).
   Nothing to uncomment — this is the default behaviour.
   ----------------------------------------------------------- */

/* ── STYLE 2: Dark overlay ───────────────────────────────────
   Forces a dark appearance regardless of the selected theme.
   Un-comment the block below to activate.
   -----------------------------------------------------------
.landing1 {
  background: #16213e;
}
.landing1 .plan-card {
  background: #1a1a2e;
  border-color: #374151;
  box-shadow: 0 2px 8px rgba(0,0,0,.4);
}
.landing1 .plan-card:hover {
  border-color: #60a5fa;
  box-shadow: 0 8px 24px rgba(0,0,0,.6);
}
.landing1 .plan-name   { color: #f3f4f6; }
.landing1 .plan-price  { color: #60a5fa; }
.landing1 .billing-period   { color: #9ca3af; }
.landing1 .plan-description { color: #9ca3af; }
.landing1 .choose-plan-btn  { background: #60a5fa; }
.landing1 .choose-plan-btn:hover { background: #3b82f6; }
.landing1-header h1  { color: #f3f4f6; }
.landing1 .subtitle  { color: #9ca3af; }
   ----------------------------------------------------------- */

/* ── STYLE 3: Light-clean (ocean palette) ────────────────────
   Crisp white cards on a light blue tint. Good for pricing
   pages that sit outside the authenticated dashboard.
   Un-comment the block below to activate.
   -----------------------------------------------------------
.landing1 {
  background: #f0f9ff;
}
.landing1 .plan-card {
  background: #ffffff;
  border-radius: 16px;
  border-color: transparent;
  box-shadow: 0 4px 20px rgba(0,0,0,.06);
}
.landing1 .plan-card:hover {
  border-color: #0284c7;
  box-shadow: 0 8px 28px rgba(2,132,199,.15);
}
.landing1 .plan-name   { color: #0c4a6e; }
.landing1 .plan-price  { color: #0284c7; }
.landing1 .billing-period   { color: #64748b; }
.landing1 .plan-description { color: #64748b; }
.landing1 .choose-plan-btn  { background: #0284c7; }
.landing1 .choose-plan-btn:hover { background: #0369a1; }
.landing1-header h1  { color: #0c4a6e; }
.landing1 .subtitle  { color: #64748b; }
   ----------------------------------------------------------- */
"""

NATIVE_PRICING_CONFIG = {
    "component": "NativePricingPlans",
    "component_name": "NativePricingPlans",
    "mode": "category",
    "category": "root",
    "plan_slugs": [],
    # 'teal' is one of Landing1View's ALLOWED_THEMES; 'pro' is a real seeded plan
    # slug in the 'root' category, so the featured badge/border lands on a card.
    # heading/subtitle/cta_label/highlight_badge and image_url are deliberately
    # left UNSET: the first four fall back to i18n keys present in all 8 locales,
    # and image_url would be a dangling reference on a fresh (no media) install.
    "theme": "teal",
    "highlight_slug": "pro",
    "features": NATIVE_PRICING_FEATURES,
    "css": NATIVE_PRICING_CSS,
}

# S109: theme-aware via --vbwd-* roles; light fallbacks == original values so
# the default theme is visually unchanged on every vertical.
BREADCRUMBS_CSS = (
    ".cms-breadcrumb {\n"
    "    display: flex;\n"
    "    align-items: center;\n"
    "    flex-wrap: wrap;\n"
    "    gap: 4px;\n"
    "    font-size: 0.7rem;\n"
    "    color: var(--vbwd-text-muted, #6b7280);\n"
    "    padding: 8px 0 0.25rem;\n"
    "}\n"
    ".cms-breadcrumb a, .cms-breadcrumb__link { color: var(--vbwd-color-primary, #3498db); text-decoration: none; }\n"
    ".cms-breadcrumb a:hover, .cms-breadcrumb__link:hover { text-decoration: underline; }\n"
    ".cms-breadcrumb__separator { color: var(--vbwd-text-muted, #9ca3af); user-select: none; }\n"
    ".cms-breadcrumb__current { color: var(--vbwd-text-body, #374151); font-weight: 500; }"
)

BREADCRUMBS_CONFIG = {
    "component_name": "CmsBreadcrumb",
    "separator": "/",
    "root_name": "Home",
    "root_slug": "/",
    "show_category": False,
    "max_label_length": 60,
    "category_label": "Software",
    "css": BREADCRUMBS_CSS,
}

CONTACT_FORM_CONFIG = {
    "component_name": "ContactForm",
    "recipient_email": "root@localhost.local",
    "success_message": "Thank you! Your message has been sent.",
    "fields": [
        {"id": "name", "type": "text", "label": "Name", "required": True},
        {"id": "email", "type": "email", "label": "Email", "required": True},
        {"id": "field_1", "type": "textarea", "label": "Message", "required": False},
    ],
    "rate_limit_enabled": True,
    "rate_limit_max": 5,
    "rate_limit_window_minutes": 60,
    "captcha_html": "",
    "analytics_html": "",
    "css": (
        ".contact-form-widget {\n"
        "    background: #ebe8eb;\n"
        "    border-radius: 10px;\n"
        "    margin-bottom: 5rem;\n"
        "}"
    ),
}

# S87 — GDPR/DSGVO Cookie Consent widget. Settings ride the CmsWidget.config
# JSON (no model/migration change); the fe-admin descriptor edits the same keys.
# `necessary` is implicit/locked regardless of the list.
COOKIE_CONSENT_CONFIG = {
    "component_name": "CookieConsent",
    "consent_version": 1,
    "privacy_policy_url": "/privacy",
    "position": "center",  # "center" (popup) | "bottom" (bar)
    "additional_text": "",
    "backdrop_opacity": 0.55,  # site "blend" dim, 0..1
    "categories": ["necessary", "statistics", "marketing", "preferences"],
    "show_settings_button": True,
    "debug_mode": False,
}

TESTIMONIALS_HTML = """
<section class="testimonials">
  <div class="container">
    <h2 class="testimonials__title">Loved by developers</h2>
    <div class="testimonials__grid">
      <blockquote class="testimonial">
        <p>"Switched from our old stack in a weekend. The DX is unmatched and our deploy time dropped by 80%."</p>
        <cite>— Sarah K., Lead Engineer at Acme</cite>
      </blockquote>
      <blockquote class="testimonial">
        <p>"Best decision we made this year. The team was shipping features in hours instead of days."</p>
        <cite>— Marco P., CTO at Buildfast</cite>
      </blockquote>
      <blockquote class="testimonial">
        <p>"Security audit passed first try. The built-in compliance tools saved us weeks of work."</p>
        <cite>— Jennifer L., VP Engineering at DataCo</cite>
      </blockquote>
    </div>
  </div>
</section>
<style>
.testimonials { padding: 5rem 0; }
.testimonials__title { text-align: center; font-size: 2rem; margin-bottom: 3rem; }
.testimonials__grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 1.5rem; }
.testimonial { margin: 0; padding: 2rem; border-radius: 12px; background: var(--color-surface, #f8fafc); border-left: 4px solid var(--color-primary, #2563eb); }  # noqa: E501
.testimonial p { font-size: 1rem; font-style: italic; margin-bottom: 1rem; opacity: 0.9; }
.testimonial cite { font-size: 0.875rem; opacity: 0.65; font-style: normal; font-weight: 600; }
</style>
"""

STANDARD_CONTENT_HTML = """
<h1>About VBWD</h1>
<p>VBWD is an open-source SaaS platform that gives developers and agencies a production-ready foundation for subscription businesses — without the months of boilerplate. Install it, extend it with plugins, and ship your product.</p>  # noqa: E501

<h2>What We Build</h2>
<p>VBWD is a full-stack SDK: a Python/Flask backend, a Vue 3 admin panel, and a Vue 3 user-facing frontend. Everything communicates through a clean REST API and is designed to be extended through a plugin system.</p>  # noqa: E501
<ul>
  <li><strong>Subscription billing</strong> — Stripe, PayPal, and YooKassa ship out of the box</li>
  <li><strong>User management</strong> — registration, login, roles, profiles, invoices</li>
  <li><strong>CMS</strong> — pages, layouts, widgets, styles — all manageable from the admin panel</li>
  <li><strong>Plugin system</strong> — add features without touching core code</li>
</ul>

<h2>Our Philosophy</h2>
<p>We believe the foundation of a SaaS product should be open, auditable, and yours to own. No vendor lock-in, no black boxes. VBWD is released under CC0 — do whatever you want with it.</p>  # noqa: E501

<h2>Community &amp; Support</h2>
<p>VBWD is built in the open. Contributions, bug reports, and feature requests are welcome on GitHub. For commercial support, managed hosting, and custom plugin development, check our plans below.</p>  # noqa: E501

<h2>Contact</h2>
<p>Questions? Reach us at <a href="mailto:hello@vbwd.dev">hello@vbwd.dev</a> or open an issue on GitHub.</p>
"""

STANDARD_CONTENT_JSON = {
    "type": "doc",
    "content": [
        {
            "type": "heading",
            "attrs": {"level": 1},
            "content": [{"type": "text", "text": "About VBWD"}],
        },
        {
            "type": "paragraph",
            "content": [
                {
                    "type": "text",
                    "text": "VBWD is an open-source SaaS platform that gives developers and agencies a production-ready foundation for subscription businesses — without the months of boilerplate. Install it, extend it with plugins, and ship your product.",  # noqa: E501
                }
            ],
        },
        {
            "type": "heading",
            "attrs": {"level": 2},
            "content": [{"type": "text", "text": "What We Build"}],
        },
        {
            "type": "paragraph",
            "content": [
                {
                    "type": "text",
                    "text": "VBWD is a full-stack SDK: a Python/Flask backend, a Vue 3 admin panel, and a Vue 3 user-facing frontend. Everything communicates through a clean REST API and is designed to be extended through a plugin system.",  # noqa: E501
                }
            ],
        },
        {
            "type": "bulletList",
            "content": [
                {
                    "type": "listItem",
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [
                                {
                                    "type": "text",
                                    "text": "Subscription billing — Stripe, PayPal, and YooKassa ship out of the box",
                                }
                            ],
                        }
                    ],
                },
                {
                    "type": "listItem",
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [
                                {
                                    "type": "text",
                                    "text": "User management — registration, login, roles, profiles, invoices",
                                }
                            ],
                        }
                    ],
                },
                {
                    "type": "listItem",
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [
                                {
                                    "type": "text",
                                    "text": "CMS — pages, layouts, widgets, styles — all manageable from the admin panel",  # noqa: E501
                                }
                            ],
                        }
                    ],
                },
                {
                    "type": "listItem",
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [
                                {
                                    "type": "text",
                                    "text": "Plugin system — add features without touching core code",
                                }
                            ],
                        }
                    ],
                },
            ],
        },
        {
            "type": "heading",
            "attrs": {"level": 2},
            "content": [{"type": "text", "text": "Our Philosophy"}],
        },
        {
            "type": "paragraph",
            "content": [
                {
                    "type": "text",
                    "text": "We believe the foundation of a SaaS product should be open, auditable, and yours to own. No vendor lock-in, no black boxes. VBWD is released under CC0 — do whatever you want with it.",  # noqa: E501
                }
            ],
        },
        {
            "type": "heading",
            "attrs": {"level": 2},
            "content": [{"type": "text", "text": "Community & Support"}],
        },
        {
            "type": "paragraph",
            "content": [
                {
                    "type": "text",
                    "text": "VBWD is built in the open. Contributions, bug reports, and feature requests are welcome on GitHub. For commercial support, managed hosting, and custom plugin development, check our plans below.",  # noqa: E501
                }
            ],
        },
        {
            "type": "heading",
            "attrs": {"level": 2},
            "content": [{"type": "text", "text": "Contact"}],
        },
        {
            "type": "paragraph",
            "content": [
                {
                    "type": "text",
                    "text": "Questions? Reach us at hello@vbwd.dev or open an issue on GitHub.",
                }
            ],
        },
    ],
}

# ─── Standalone vue-component widgets ───────────────────────────────────────────
# These widgets are registered in fe-user (vueComponentRegistry) and have
# fe-admin editor descriptors, but had no seeded RECORD — so they never showed
# up in the admin widget picker (which lists widget records from the DB). Each
# is seeded as a standalone vue-component widget; appearing in the picker is
# enough (they need not be placed on a layout). Single source of truth: the
# seeder iterates this list. The ``config`` blocks mirror the fe-admin editor
# defaults (plugins/cms-admin/src/widgets/index.ts).
_STANDALONE_VUE_WIDGETS = [
    {
        "slug": "code-snippet",
        "name": "Code Snippet (HTML/JS)",
        "widget_type": "vue-component",
        "content_json": {"component": "CustomCode"},
        "config": {
            "component_name": "CustomCode",
            "code": "<!-- paste analytics / counter <script> here -->",
        },
    },
    {
        "slug": "category",
        "name": "Category (Term Post List)",
        "widget_type": "vue-component",
        "content_json": {"component": "Category"},
        "config": {
            "component_name": "Category",
            "type": "post",
            "term_type": "category",
            "term_slug": "",
            "mode": "titles",
            "limit": 10,
            "paginate": False,
        },
    },
    {
        "slug": "search",
        "name": "Search Box",
        "widget_type": "vue-component",
        "content_json": {"component": "Search"},
        "config": {
            "component_name": "Search",
            "placeholder": "Search…",
            "target_path": "",
            # S121 — constrained scope + quicksearch controls. ``both`` searches
            # all published types (pages + posts); quicksearch off by default so
            # existing operator-placed boxes are byte-identical to before.
            "scope": "both",
            "quicksearch": False,
            "quicksearch_limit": 6,
        },
    },
    {
        "slug": "search-results",
        "name": "Search Results",
        "widget_type": "vue-component",
        "content_json": {"component": "SearchResults"},
        "config": {
            "component_name": "SearchResults",
            # S121 — ``scope`` (pages | posts | both) replaces the legacy
            # free-text ``type``. ``both`` omits the post-type filter server-side.
            "scope": "both",
            # S120 — default the fresh-install results to the WordPress-archive
            # ``category`` card (fe-user SearchResults supports mode='category');
            # existing widgets are untouched (this only shapes newly-created rows).
            "mode": "category",
            "per_page": 8,
        },
    },
    {
        # A SECOND SearchResults record — the docs/pages-scoped split. Same
        # ``SearchResults`` vue component as ``search-results`` above, but the
        # query is constrained to pages only (``types: ['page']``) so operators
        # get a ready-made "docs search" widget in the admin picker. The general
        # ``search-results`` record stays the broad content search.
        "slug": "search-results-docs",
        "name": "Search Results — Docs",
        "widget_type": "vue-component",
        "content_json": {"component": "SearchResults"},
        "config": {
            "component_name": "SearchResults",
            "types": ["page"],
            "mode": "category",
            "per_page": 8,
        },
    },
    # Pure-frontend catalog widgets — they consume EXISTING public catalog APIs
    # (GET /tarif-plans?category=<slug> / GET /tarif-plans/<slug> for plans;
    # GET /token-bundles/ for bundles). No backend endpoint or per-widget
    # backend logic is added here; the seeds only create the picker RECORDS.
    {
        "slug": "tariff-plan-collection",
        "name": "Tariff Plan Collection",
        "widget_type": "vue-component",
        "content_json": {"component": "TariffPlanCollection"},
        "config": {
            "component_name": "TariffPlanCollection",
            "source_mode": "category",
            "category": "root",
            "plan_slugs": [],
            "default_view": "cards",
            "heading": "",
            # Default pricing-card styling (shared with NativePricingPlans):
            # 'teal' theme + the shared feature bullets are universally safe, and
            # this is a 'root'-category widget — the only category with a 'pro'
            # plan — so 'pro' resolves to a real card here.
            "theme": "teal",
            "highlight_slug": "pro",
            "features": NATIVE_PRICING_FEATURES,
        },
    },
    {
        "slug": "token-bundle-collection",
        "name": "Token Bundle Collection",
        "widget_type": "vue-component",
        "content_json": {"component": "TokenBundleCollection"},
        "config": {
            "component_name": "TokenBundleCollection",
            "bundle_ids": [],
            "default_view": "cards",
            "heading": "",
        },
    },
    # S87 — GDPR/DSGVO Cookie Consent. The seed only creates the picker RECORD;
    # an admin drops it into a layout area (the widget renders as a body overlay,
    # so the area is irrelevant). No backend endpoint or per-widget logic.
    {
        "slug": "cookie-consent",
        "name": "Cookie Consent (GDPR/DSGVO)",
        "widget_type": "vue-component",
        "content_json": {"component": "CookieConsent"},
        "config": COOKIE_CONSENT_CONFIG,
    },
    # Super Header — a composite header that fetches a nested `menu` widget by
    # slug at render time (via the public /api/v1/cms/widgets/by-slug route).
    # The seed only creates the picker RECORD; operators place it themselves (it
    # is deliberately NOT added to _LAYOUT_WIDGET_PLACEMENTS).
    {
        "slug": "super-header",
        "name": "Super Header",
        "widget_type": "vue-component",
        "content_json": {"component": "SuperHeader"},
        "config": {
            "component_name": "SuperHeader",
            "logo_image_url": "",
            "logo_text": "VBWD",
            "logo_link": "/",
            "nav_widget_slug": "header-nav",
            "show_search": True,
            "search_placeholder": "Search…",
            "search_target_path": "/search",
            "search_scope": "both",
            "quicksearch": True,
            "quicksearch_limit": 6,
            "show_auth_links": True,
            "login_label": "Login",
            "login_path": "/login",
            "dashboard_label": "Dashboard",
            "dashboard_path": "/dashboard",
            "stickable": False,
            "stickable_offset_px": 160,
        },
    },
]


# ─── Layouts ───────────────────────────────────────────────────────────────────

# Layouts are authored as JSON in docs/imports/layouts/ — re-imported on each
# populator run. Edit those files, not this script.
_LAYOUTS_DIR = _THEMES_PATH.parent / "layouts"
_PAGES_DIR = _THEMES_PATH.parent / "pages"

# Default layout → widget placements, keyed by layout slug then ``area_name``.
# The S46 ``cms_layouts`` envelope only carries the layout's own columns (slug,
# name, areas, …) — the layout↔widget PLACEMENT is a separate join table
# (cms_layout_widget) the envelope cannot carry, and it is a *seeder* concern
# (which demo widget lands in which default-layout area). Each value is
# (area_name, widget_slug); order is the seeded sort_order.
_LAYOUT_WIDGET_PLACEMENTS: dict[str, list[tuple[str, str]]] = {
    "contact-form": [
        ("header", "header-nav"),
        ("contact form", "contact-form"),
        ("footer", "footer-nav"),
    ],
    "content-page": [
        ("header", "header-nav"),
        ("breadcrumbs", "breadcrumbs"),
        ("footer", "footer-nav"),
        # S87 — GDPR/DSGVO consent overlay. Mounted in its own `consent` vue
        # area (Teleports to body, so the area is just a mount point); placing
        # it on the default content-page layout makes it site-wide.
        ("consent", "cookie-consent"),
    ],
    "ghrm-software-catalogue": [
        ("header", "header-nav"),
        ("breadcrumbs", "breadcrumbs"),
        ("ghrm-categories", "ghrm-categories"),
        ("footer", "footer-nav"),
    ],
    "ghrm-software-detail": [
        ("header", "header-nav"),
        ("breadcrumbs", "breadcrumbs"),
        ("ghrm-software-detail", "ghrm-software-detail"),
        ("footer", "footer-nav"),
    ],
    "home-v1": [
        ("header", "header-nav"),
        ("hero", "hero-home1"),
        ("features", "features-3col"),
        ("cta", "cta-primary"),
        ("footer", "footer-nav"),
    ],
    "home-v2": [
        ("header", "header-nav"),
        ("hero", "hero-home2"),
        ("pricing", "pricing-2col"),
        ("testimonials", "testimonials"),
        ("footer", "footer-nav"),
    ],
    "landing": [
        ("header", "header-nav"),
        ("hero", "hero-home1"),
        ("features", "features-3col"),
        ("cta", "cta-primary"),
        ("social-proof", "testimonials"),
        ("footer", "footer-nav"),
    ],
    "native-pricing-page": [
        ("header", "header-nav"),
        ("main", "pricing-native-plans"),
        ("footer", "footer-nav"),
    ],
    # Public vertical landing pages: /tarifs reuses the existing
    # `native-pricing-page` layout and /soft reuses `ghrm-software-catalogue`
    # (same precedent as the `category` page) — no duplicate layouts. Only
    # /addons needs a new layout, hosting the new AddonCatalog widget.
    "addons": [
        ("header", "header-nav"),
        ("breadcrumbs", "breadcrumbs"),
        ("addons", "addon-catalog"),
        ("footer", "footer-nav"),
    ],
    "tag-archive": [
        ("header", "header-nav"),
        ("breadcrumbs", "breadcrumbs"),
        ("archive", "tag-archive"),
        ("footer", "footer-nav"),
    ],
    # Posts archive (blog index): the PostArchive widget lists ALL published
    # posts (no term filter) through the existing GET /cms/posts?type=post path.
    "posts-archive": [
        ("header", "header-nav"),
        ("breadcrumbs", "breadcrumbs"),
        ("archive", "posts-archive"),
        ("footer", "footer-nav"),
    ],
    # Shared term archive: ONE layout renders every category AND tag archive.
    # The route-driven TermArchive widget reads the term type + slug from the
    # catch-all URL (/category/<slug> or /tag/<slug>) and lists that term's posts.
    "terms-archive": [
        ("header", "header-nav"),
        ("breadcrumbs", "breadcrumbs"),
        ("archive", "terms-archive"),
        ("footer", "footer-nav"),
    ],
    # S121 — demo search layouts. The Search / SearchResults widgets are placed
    # at PAGE level (via config_override on the docs/search demo pages), so only
    # the structural header/footer are layout-level placements here.
    "docs": [
        ("header", "header-nav"),
        ("footer", "footer-nav"),
    ],
    "search": [
        ("header", "header-nav"),
        ("footer", "footer-nav"),
    ],
}


def _translate_layout_row(row: dict) -> dict:
    """Attach the seeder-owned widget placements to an S46 ``cms_layouts`` row.

    The envelope row already carries the layout columns; ``_get_or_create_layout``
    additionally reads ``widget_assignments`` (a list of (area, widget_slug)),
    sourced here from the placement constant.
    """
    translated = dict(row)
    translated["widget_assignments"] = _LAYOUT_WIDGET_PLACEMENTS.get(
        row.get("slug", ""), []
    )
    return translated


def _translate_page_row(row: dict) -> dict:
    """Translate an S46 ``cms_posts`` (page) row back into the field names the
    seeder's page helpers expect: title→name, status→is_published,
    terms→category_slug, page_assignments→page_widget_assignments.
    """
    translated = dict(row)
    translated["name"] = row.get("name") or row.get("title", "")
    status = row.get("status")
    if status is not None:
        translated["is_published"] = status == "published"
    if "category_slug" not in translated:
        categories = [
            term.get("slug")
            for term in row.get("terms", [])
            if term.get("term_type") == "category" and term.get("slug")
        ]
        translated["category_slug"] = categories[0] if categories else None
    if "page_widget_assignments" not in translated:
        translated["page_widget_assignments"] = row.get("page_assignments", [])
    return translated


def _load_layouts() -> list[dict]:
    if not _LAYOUTS_DIR.exists():
        print(f"  WARN: layouts dir missing at {_LAYOUTS_DIR} — no layouts imported")
        return []
    items: list[dict] = []
    for p in sorted(_LAYOUTS_DIR.glob("*.json")):
        doc = _json.loads(p.read_text())
        for row in _unwrap_envelope(doc, "cms_layouts") or [doc]:
            items.append(_translate_layout_row(row))
    return items


def _load_pages() -> list[dict]:
    if not _PAGES_DIR.exists():
        print(f"  WARN: pages dir missing at {_PAGES_DIR} — no pages imported")
        return []
    items: list[dict] = []
    for p in sorted(_PAGES_DIR.glob("*.json")):
        doc = _json.loads(p.read_text())
        for row in _unwrap_envelope(doc, "cms_posts") or [doc]:
            items.append(_translate_page_row(row))
    return items


LAYOUTS = _load_layouts()


# ─── Main ──────────────────────────────────────────────────────────────────────


def _get_or_create_style(slug: str, data: dict) -> "CmsStyle":
    is_active = bool(data.get("is_active", True))
    existing = db.session.query(CmsStyle).filter_by(slug=slug).first()
    if existing:
        existing.name = data["name"]
        existing.source_css = data["source_css"]
        existing.sort_order = data.get("sort_order", 0)
        existing.is_active = is_active
        db.session.flush()
        print(f"  ~ style '{slug}' (updated)")
        return existing
    obj = CmsStyle(
        slug=slug,
        name=data["name"],
        source_css=data["source_css"],
        sort_order=data.get("sort_order", 0),
        is_active=is_active,
    )
    db.session.add(obj)
    db.session.flush()
    print(f"  + style '{slug}'")
    return obj


def _deactivate_legacy_styles(slugs: list[str], keep: set[str]) -> int:
    """Mark legacy style slugs inactive so they drop out of admin pickers.

    Skips any slug that's in `keep` (i.e. still part of the imported set).
    Idempotent: returns the number of rows flipped.
    """
    flipped = 0
    for slug in slugs:
        if slug in keep:
            continue
        obj = db.session.query(CmsStyle).filter_by(slug=slug).first()
        if obj is not None and obj.is_active:
            obj.is_active = False
            flipped += 1
            print(f"  ~ legacy style '{slug}' marked is_active=false")
    if flipped:
        db.session.flush()
    return flipped


def _apply_default_style(default_slug: Optional[str]) -> None:
    """Flip is_default on the configured default; zero on everything else.

    Keeps the partial-unique-index invariant.
    """
    if not default_slug:
        return
    target = db.session.query(CmsStyle).filter_by(slug=default_slug).first()
    if target is None:
        print(f"  WARN: default slug '{default_slug}' not found — skipping")
        return
    # Demote any current default(s) FIRST, flush, THEN promote the target
    # — the partial unique index on is_default would otherwise raise on
    # the batched executemany (both rows temporarily have is_default=t).
    current = db.session.query(CmsStyle).filter_by(is_default=True).all()
    need_demote = [c for c in current if str(c.id) != str(target.id)]
    if need_demote:
        for c in need_demote:
            c.is_default = False
        db.session.flush()
    if not target.is_default:
        target.is_default = True
        db.session.flush()
    print(f"  ★ default style set to '{default_slug}'")


def _get_or_create_widget(
    slug: str,
    name: str,
    widget_type: str,
    content_html: Optional[str] = None,
    content_json: Optional[dict] = None,
    source_css: Optional[str] = None,
    config: Optional[dict] = None,
) -> "CmsWidget":
    if widget_type == "html" and content_html is not None:
        content_json, extracted_css = _split_widget_content(content_html)
        source_css = source_css or extracted_css
    existing = db.session.query(CmsWidget).filter_by(slug=slug).first()
    if existing:
        existing.name = name
        if widget_type == "html":
            existing.content_json = content_json
        elif content_json is not None:
            existing.content_json = content_json
        if source_css is not None:
            existing.source_css = source_css
        if config is not None:
            existing.config = config
        db.session.flush()
        print(f"  ~ widget '{slug}' (updated)")
        return existing
    obj = CmsWidget(
        slug=slug,
        name=name,
        widget_type=widget_type,
        content_json=content_json,
        source_css=source_css,
        config=config,
        sort_order=0,
        is_active=True,
    )
    db.session.add(obj)
    db.session.flush()
    print(f"  + widget '{slug}' ({widget_type})")
    return obj


def _clear_menu_items(widget: "CmsWidget") -> None:
    """Delete all menu items for a widget (including nested children)."""
    db.session.query(CmsMenuItem).filter_by(widget_id=widget.id).delete()
    db.session.flush()


def _add_menu_items(widget: "CmsWidget", items: list) -> None:
    """Add menu items to a widget. Items may include a 'children' key for submenus."""
    for i, item in enumerate(items):
        mi = CmsMenuItem(
            widget_id=widget.id,
            parent_id=None,
            label=item["label"],
            url=item.get("url"),
            page_slug=item.get("page_slug"),
            target=item.get("target", "_self"),
            sort_order=i,
        )
        db.session.add(mi)
        db.session.flush()  # get mi.id before creating children
        for j, child in enumerate(item.get("children", [])):
            child_mi = CmsMenuItem(
                widget_id=widget.id,
                parent_id=mi.id,
                label=child["label"],
                url=child.get("url"),
                page_slug=child.get("page_slug"),
                target=child.get("target", "_self"),
                sort_order=j,
            )
            db.session.add(child_mi)


def _get_or_create_layout(data: dict, widget_map: dict) -> "CmsLayout":
    slug = data["slug"]
    existing = db.session.query(CmsLayout).filter_by(slug=slug).first()
    if existing:
        existing.name = data["name"]
        existing.description = data.get("description")
        existing.areas = data["areas"]
        existing.sort_order = data.get("sort_order", 0)
        db.session.flush()
        print(f"  ~ layout '{slug}' (updated)")
        return existing
    layout = CmsLayout(
        slug=slug,
        name=data["name"],
        description=data.get("description"),
        areas=data["areas"],
        sort_order=data.get("sort_order", 0),
        is_active=True,
    )
    db.session.add(layout)
    db.session.flush()
    # Assign widgets
    for order, (area_name, widget_slug) in enumerate(
        data.get("widget_assignments", [])
    ):
        widget = widget_map.get(widget_slug)
        if not widget:
            print(f"    ! widget '{widget_slug}' not found, skipping assignment")
            continue
        lw = CmsLayoutWidget(
            layout_id=layout.id,
            widget_id=widget.id,
            area_name=area_name,
            sort_order=order,
        )
        db.session.add(lw)
    print(f"  + layout '{slug}'")
    return layout


# ─── Posts archive (blog index) ─────────────────────────────────────────────────
# The archive is a cms_post(type=page) seeded at the config-driven ``posts_root``
# slug whose layout hosts the PostArchive widget. Constants shared with the
# integration oracle so the layout/widget slugs cannot drift.
POSTS_ARCHIVE_LAYOUT_SLUG = "posts-archive"
POSTS_ARCHIVE_WIDGET_SLUG = "posts-archive"

# Shared term-archive (category + tag) layout/widget slugs. The archive is
# served dynamically through the fe catch-all — NO per-term page is seeded —
# so only the layout + its route-driven TermArchive widget need seeding.
TERMS_ARCHIVE_LAYOUT_SLUG = "terms-archive"
TERMS_ARCHIVE_WIDGET_SLUG = "terms-archive"

# Canonical route-driven TermArchive widget definition — the single source of
# truth for BOTH the seeder (``populate_cms``) and the create-only applier
# (``apply_terms_archive_layout``), so the two can never drift. The widget reads
# the term type + slug from the catch-all route (NOT config), so ONE widget on
# the ONE terms-archive layout renders every category and tag archive.
TERMS_ARCHIVE_WIDGET_NAME = "Term Archive"
TERMS_ARCHIVE_WIDGET_CONTENT_JSON = {
    "component": "TermArchive",
    "mode": "category",
    "type": "post",
}
TERMS_ARCHIVE_WIDGET_CONFIG = {
    "component_name": "TermArchive",
    "type": "post",
    "mode": "category",
    "posts_per_page": 20,
    "paginate": True,
}


def terms_archive_layout_row() -> Optional[dict]:
    """The canonical ``terms-archive`` layout row (areas + widget placements).

    Returns the translated bundled ``terms-archive`` layout row — its ``areas``,
    ``name``, ``description``, ``sort_order`` plus the seeder-owned
    ``widget_assignments`` — or ``None`` when the bundled layout JSON is missing.
    Shared with the create-only applier so the layout definition has ONE home.
    """
    for row in LAYOUTS:
        if row.get("slug") == TERMS_ARCHIVE_LAYOUT_SLUG:
            return row
    return None


def _resolve_posts_root() -> str:
    """Resolve the archive slug (``posts_root``) from the aggregated CMS config.

    Reads the SAME source the runtime reads — ``current_app.config_store
    .get_config('cms')`` (the operator's saved overrides) — falling back to the
    bundled default ``blog`` (``DEFAULT_POSTS_ROOT``). Reading the aggregated
    config, not only the bundled ``config.json`` default, keeps the seeded
    archive page slug in lock-step with the runtime ``%root%`` permalink segment
    and avoids the "seed reads bundled config, runtime reads aggregated → 404"
    trap.
    """
    from flask import current_app
    from plugins.cms.src.services.permalink import DEFAULT_POSTS_ROOT

    config_store = getattr(current_app, "config_store", None)
    if config_store is not None:
        cms_config = config_store.get_config("cms") or {}
        posts_root = str(cms_config.get("posts_root") or "").strip()
        if posts_root:
            return posts_root
    return DEFAULT_POSTS_ROOT


def _seed_posts_archive_page(
    post_service, post_repo, layout_map: dict[str, "CmsLayout"]
) -> Optional[dict]:
    """Seed the posts-archive (blog index) page at the configured ``posts_root``.

    Create-only / idempotent by slug via ``_get_or_create_unified_page`` — never
    overwrites an existing operator page. The page body is empty; its layout
    hosts the PostArchive widget that renders the listing.
    """
    posts_root = _resolve_posts_root()
    archive_layout = layout_map.get(POSTS_ARCHIVE_LAYOUT_SLUG)
    if archive_layout is None:
        print(
            f"  ! layout '{POSTS_ARCHIVE_LAYOUT_SLUG}' missing — archive page skipped"
        )
        return None
    return _get_or_create_unified_page(
        post_service,
        post_repo,
        posts_root,
        "Blog",
        archive_layout,
        None,
        content_json={"type": "doc", "content": []},
        meta_description="All published blog posts.",
        is_published=True,
    )


def _get_or_create_category_term(
    term_service, term_repo, slug: str, name: str, sort_order: int = 0
) -> Optional[dict]:
    """Create a ``cms_term(term_type=category)`` for a demo category, idempotently.

    Returns the term dict (existing or freshly created). Re-runs hit the slug
    guard and resolve the existing term instead of creating a duplicate.
    """
    from plugins.cms.src.services.term_service import TermSlugConflictError
    from plugins.cms.src.models.cms_term import CATEGORY_TERM_TYPE

    try:
        term = term_service.create_term(
            {
                "term_type": CATEGORY_TERM_TYPE,
                "slug": slug,
                "name": name,
                "sort_order": sort_order,
            }
        )
        print(f"  + category '{slug}'")
        return term
    except TermSlugConflictError:
        existing = term_repo.find_by_type_and_slug(CATEGORY_TERM_TYPE, slug)
        print(f"  ~ category '{slug}' (exists)")
        return existing.to_dict() if existing else None


def _get_or_create_unified_page(
    post_service,
    post_repo,
    slug: str,
    name: str,
    layout: Optional["CmsLayout"],
    style: Optional["CmsStyle"],
    content_json: Optional[dict] = None,
    content_html: Optional[str] = None,
    meta_description: Optional[str] = None,
    sort_order: int = 0,
    robots: str = "index,follow",
    is_published: bool = True,
) -> Optional[dict]:
    """Create a unified ``cms_post(type=page)`` for a demo page, idempotently.

    Returns the post dict (existing or freshly created), or ``None`` if it could
    neither be created nor resolved. Re-runs hit the service's slug guard and
    resolve the existing post (via the repo, which sees drafts too) instead of
    creating a duplicate.
    """
    from plugins.cms.src.services.post_service import PostSlugConflictError
    from plugins.cms.src.models.cms_post import (
        POST_STATUS_PUBLISHED,
        POST_STATUS_DRAFT,
    )

    data = {
        "type": "page",
        "slug": slug,
        "title": name,
        "language": "en",
        "content_json": content_json or {"type": "doc", "content": []},
        "content_html": content_html,
        "sort_order": sort_order,
        "robots": robots,
        "meta_title": name,
        "meta_description": meta_description or name,
        "status": POST_STATUS_PUBLISHED if is_published else POST_STATUS_DRAFT,
        "layout_id": str(layout.id) if layout else None,
        "style_id": str(style.id) if style else None,
    }
    try:
        post = post_service.create_post(data)
        print(f"  + page '{slug}' (layout={layout.slug if layout else None})")
        return post
    except PostSlugConflictError:
        existing = post_repo.find_by_type_and_slug("page", slug.strip("/"))
        print(f"  ~ page '{slug}' (exists)")
        return existing.to_dict() if existing else None


def _set_unified_page_widgets(
    post_widget_repo,
    post: dict,
    assignments: list[dict],
    widget_map: dict[str, "CmsWidget"],
) -> None:
    """Assign page-level widgets to a unified post. Idempotent — skips if the
    post already has assignments (replace would otherwise re-write them).

    ``assignments`` mirror the demo pages' ``page_widget_assignments`` shape:
    dicts with ``widget_slug`` / ``area_name`` and an optional per-placement
    ``config_override`` (S121 — e.g. the docs-layout quicksearch box)."""
    post_id = post["id"]
    if post_widget_repo.find_by_post(post_id):
        return
    rows: list[dict] = []
    for order, assignment in enumerate(assignments):
        widget_slug = assignment["widget_slug"]
        widget = widget_map.get(widget_slug)
        if not widget:
            print(f"    ! widget '{widget_slug}' not found, skipping")
            continue
        rows.append(
            {
                "widget_id": str(widget.id),
                "area_name": assignment["area_name"],
                "sort_order": assignment.get("sort_order", order),
                "config_override": assignment.get("config_override"),
            }
        )
    if rows:
        post_widget_repo.replace_for_post(post_id, rows)
        print(f"    + {len(rows)} page widget(s) for '{post['slug']}'")


# ─── Docs page re-point (S121 Defect 2) ────────────────────────────────────────
# A real documentation-portal page already owns the ``docs`` slug on another
# layout, so the create-only page path (which skips on a slug conflict) never
# gives it the quicksearch sidebar. This is the ONE sanctioned mutation of that
# live page: re-point its layout + ensure the sidebar Search box — nothing else.
_DOCS_PAGE_SLUG = "docs"
_DOCS_LAYOUT_SLUG = "docs"
_DOCS_SEARCH_AREA = "sidebar"
_DOCS_SEARCH_WIDGET_SLUG = "search"
# Defect 1 — vue-component overrides are nested under ``config`` so the fe-user
# renderer (which merges ``override.config``) actually applies them.
_DOCS_QUICKSEARCH_CONFIG_OVERRIDE = {
    "config": {"quicksearch": True, "scope": "both", "quicksearch_limit": 6}
}


def _repoint_docs_page_to_docs_layout(
    post_repo, post_widget_repo, layout_map, widget_map
) -> None:
    """Idempotently re-point the EXISTING ``docs`` page onto the "Docs pages"
    layout and ensure its sidebar holds a quicksearch Search box.

    Narrow + idempotent: it changes ONLY the page's ``layout_id`` (when it
    differs) and appends the sidebar Search assignment (with the nested
    ``config_override``) when absent — the title, body, SEO and any other page
    widgets are left untouched, so re-pointing never blanks the documentation.
    A re-run is a no-op. Does nothing if the docs page, layout or Search widget
    is not present (e.g. a partially-seeded DB).
    """
    docs_page = post_repo.find_by_type_and_slug("page", _DOCS_PAGE_SLUG)
    docs_layout = layout_map.get(_DOCS_LAYOUT_SLUG)
    search_widget = widget_map.get(_DOCS_SEARCH_WIDGET_SLUG)
    if docs_page is None or docs_layout is None or search_widget is None:
        return

    if str(docs_page.layout_id) != str(docs_layout.id):
        docs_page.layout_id = docs_layout.id
        db.session.add(docs_page)
        db.session.flush()
        print(f"  ~ page 'docs' re-pointed to '{docs_layout.slug}' layout")

    existing = post_widget_repo.find_by_post(str(docs_page.id))

    def _is_sidebar_search(row) -> bool:
        return (
            str(row.widget_id) == str(search_widget.id)
            and row.area_name == _DOCS_SEARCH_AREA
        )

    def _is_nested(override) -> bool:
        return isinstance(override, dict) and isinstance(override.get("config"), dict)

    sidebar_rows = [row for row in existing if _is_sidebar_search(row)]
    # Idempotent: a correctly-nested sidebar Search box needs no change (and any
    # other page widgets stay exactly as the operator left them).
    if sidebar_rows and all(_is_nested(row.config_override) for row in sidebar_rows):
        return

    # Preserve every existing widget. Heal a stale FLAT sidebar override (a
    # pre-Defect-1 seed artifact the renderer silently ignored) to the canonical
    # nested shape; append the Search box if the sidebar has none.
    healed = False
    rows: list[dict] = []
    for row in existing:
        override = row.config_override
        if _is_sidebar_search(row) and not _is_nested(override):
            override = dict(_DOCS_QUICKSEARCH_CONFIG_OVERRIDE)
            healed = True
        rows.append(
            {
                "widget_id": str(row.widget_id),
                "area_name": row.area_name,
                "sort_order": row.sort_order,
                "required_access_level_ids": row.required_access_level_ids,
                "config_override": override,
            }
        )
    if not sidebar_rows:
        rows.append(
            {
                "widget_id": str(search_widget.id),
                "area_name": _DOCS_SEARCH_AREA,
                "sort_order": len(rows),
                "config_override": dict(_DOCS_QUICKSEARCH_CONFIG_OVERRIDE),
            }
        )
    post_widget_repo.replace_for_post(str(docs_page.id), rows)
    if healed:
        print("  ~ page 'docs' sidebar Search override healed to nested config")
    else:
        print("  + page 'docs' sidebar Search box ensured (quicksearch on)")


# ─── Unified model seed (S47.0) ────────────────────────────────────────────────
# Seeds cms_post / cms_term THROUGH the services (never raw SQL); idempotent —
# a re-run hits the slug-uniqueness guard and creates nothing new. Cold-CI-safe.

# Categories live on the cms_term taxonomy; tags live in the core tag catalog
# (D7) and are seeded onto hello-world via the tags port (see below).
_UNIFIED_TERMS = [
    {"term_type": "category", "slug": "news", "name": "News", "sort_order": 0},
    {"term_type": "category", "slug": "guides", "name": "Guides", "sort_order": 1},
]

_UNIFIED_POSTS = [
    {
        "type": "page",
        "slug": "about-unified",
        "title": "About (Unified)",
        "content_html": "<h1>About</h1>",
        "content_json": {"type": "doc", "content": []},
        "status": "published",
    },
    {
        "type": "page",
        "slug": "contact-unified",
        "title": "Contact (Unified)",
        "content_html": "<h1>Contact</h1>",
        "content_json": {"type": "doc", "content": []},
        "status": "published",
    },
    {
        "type": "post",
        "slug": "hello-world",
        "title": "Hello World",
        "content_html": "<p>First post.</p>",
        "content_json": {"type": "doc", "content": []},
        "status": "published",
    },
    {
        "type": "post",
        "slug": "second-post",
        "title": "Second Post",
        "content_html": "<p>Another post.</p>",
        "content_json": {"type": "doc", "content": []},
        "status": "draft",
    },
]


def seed_unified_content(post_service, term_service, tags_port) -> dict:
    """Idempotently seed the unified cms_post / cms_term model via services.

    Returns a ``{"posts_created", "terms_created", "tags_linked"}`` summary.
    A slug that
    already exists raises a *SlugConflictError from the service, which we treat
    as "already seeded" — so the seeder is safe to re-run on every deploy.
    Categories go through ``TermService``; tags go through the core tags port
    (D7).
    """
    from plugins.cms.src.services.post_service import PostSlugConflictError
    from plugins.cms.src.services.term_service import TermSlugConflictError

    terms_created = 0
    for term in _UNIFIED_TERMS:
        try:
            term_service.create_term(dict(term))
            terms_created += 1
        except TermSlugConflictError:
            continue

    posts_created = 0
    for post in _UNIFIED_POSTS:
        try:
            post_service.create_post(dict(post))
            posts_created += 1
        except PostSlugConflictError:
            continue

    # Tag the published `hello-world` post via the core catalog so the tag cloud
    # (on the post) and the tag archive (listing the post) both have data.
    # Idempotent: ``set_tags`` replaces the entity's full tag set.
    tags_linked = _link_hello_world_tags(post_service, tags_port)

    return {
        "posts_created": posts_created,
        "terms_created": terms_created,
        "tags_linked": tags_linked,
    }


_HELLO_WORLD_TAG_SLUGS = ["release", "tutorial"]
_TAG_ENTITY_TYPE = "cms_post"


def _link_hello_world_tags(post_service, tags_port) -> int:
    """Tag the `hello-world` post with `release`/`tutorial` via the core port.

    Resolves the post id through the public service surface
    (``resolve_published_path``) then writes the tags to the single core catalog
    (``set_tags`` auto-creates the catalog rows). Returns the number of tags
    set (0 when the post is absent, e.g. on a partially-seeded DB). Safe to
    re-run — ``set_tags`` replaces the entity's tag set deterministically.
    """
    post = post_service.resolve_published_path("post", "hello-world")
    if not post:
        return 0
    tags_port.set_tags(_TAG_ENTITY_TYPE, post["id"], list(_HELLO_WORLD_TAG_SLUGS))
    return len(_HELLO_WORLD_TAG_SLUGS)


def _build_unified_services():
    """Build the unified post/term services + repos from ``db.session``.

    Ensures the built-in post/term types are registered (the standalone
    ``__main__`` path does not run the plugin's ``on_enable``). Returns a tuple
    of ``(post_service, term_service, post_repo, term_repo, post_widget_repo)``
    so the demo seeds pages, terms and page-widget assignments straight through
    the unified layer (the legacy cms_page round-trip was retired in S105).
    """
    from plugins.cms.src.services import post_type_registry, term_type_registry
    from plugins.cms.src.services.post_type_registry import PostType
    from plugins.cms.src.services.term_type_registry import TermType
    from plugins.cms.src.repositories.post_repository import PostRepository
    from plugins.cms.src.repositories.term_repository import TermRepository
    from plugins.cms.src.repositories.post_term_repository import PostTermRepository
    from plugins.cms.src.repositories.cms_post_widget_repository import (
        CmsPostWidgetRepository,
    )
    from plugins.cms.src.services.post_service import PostService
    from plugins.cms.src.services.term_service import TermService

    if not post_type_registry.is_registered("page"):
        post_type_registry.register_post_type(
            PostType(key="page", label="Page", routable=True, hierarchical=True)
        )
    if not post_type_registry.is_registered("post"):
        post_type_registry.register_post_type(
            PostType(key="post", label="Post", routable=True, hierarchical=False)
        )
    if not term_type_registry.is_registered("category"):
        term_type_registry.register_term_type(
            TermType(key="category", label="Category", hierarchical=True)
        )
    # ``tag`` is no longer a cms_term taxonomy (D7) — tags live in the core
    # catalog and are seeded via the tags port.

    post_repo = PostRepository(db.session)
    term_repo = TermRepository(db.session)
    post_service = PostService(
        repo=post_repo,
        term_repo=term_repo,
        post_term_repo=PostTermRepository(db.session),
    )
    term_service = TermService(term_repo)
    post_widget_repo = CmsPostWidgetRepository(db.session)
    return post_service, term_service, post_repo, term_repo, post_widget_repo


def _seed_unified_demo_content(post_service, term_service) -> None:
    """Seed the small unified demo content set (extra posts + hello-world tags)."""
    from vbwd.services.tags_and_custom_fields import resolve_tags_and_custom_fields

    summary = seed_unified_content(
        post_service, term_service, resolve_tags_and_custom_fields()
    )
    print(
        f"  Unified     : +{summary['posts_created']} posts, "
        f"+{summary['terms_created']} terms, "
        f"{summary['tags_linked']} hello-world tags"
    )


# S120 — canonical homepage. The home post is seeded under slug ``index`` and
# rendered at ``/`` directly by the fe (no client redirect), so the old
# ``default → home1`` middleware redirect is redundant + harmful (it 404'd on a
# fresh install). Instead we retire any stale ``default`` rule and seed exact
# 301 redirects that consolidate the duplicate slug-URLs onto the canonical ``/``.
_HOME_REDIRECTS = (
    ("home-index-redirect", "/index"),
    ("home-legacy-redirect", "/home"),
)


def _get_or_create_exact_redirect(name: str, source_path: str) -> None:
    """Idempotently seed a ``path_exact`` 301 → ``/`` middleware routing rule.

    Exact (not prefix) match so ``/home`` never catches the ``/home2`` demo page.
    Keyed on ``(match_type, match_value)`` so a re-seed never duplicates.
    """
    existing = (
        db.session.query(CmsRoutingRule)
        .filter_by(match_type="path_exact", match_value=source_path)
        .first()
    )
    if existing:
        print(f"  ~ redirect: {source_path} → / (exists)")
        return
    db.session.add(
        CmsRoutingRule(
            name=name,
            match_type="path_exact",
            match_value=source_path,
            target_slug="/",
            is_active=True,
            priority=0,
            layer="middleware",
            redirect_code=301,
            is_rewrite=False,
        )
    )
    print(f"  + redirect: {source_path} → / (301)")


def _seed_home_routing_rules() -> None:
    """Converge routing rules onto the S120 canonical-home model.

    Retires any legacy ``default`` middleware rule (the fe now renders the home
    post at ``/`` directly) and seeds the ``/index`` + ``/home`` → ``/`` 301s.
    """
    retired = (
        db.session.query(CmsRoutingRule)
        .filter_by(match_type="default", layer="middleware")
        .delete()
    )
    if retired:
        print(f"  - retired {retired} legacy 'default' middleware routing rule(s)")
    for name, source_path in _HOME_REDIRECTS:
        _get_or_create_exact_redirect(name, source_path)
    db.session.commit()


def populate_cms() -> None:
    print("\n── Styles ──────────────────────────────────────────────────────")
    style_map: dict[str, "CmsStyle"] = {}
    for s in STYLES:
        style_slug = cast(str, s["slug"])
        style_map[style_slug] = _get_or_create_style(style_slug, s)
    imported_slugs = set(style_map.keys())
    _deactivate_legacy_styles(LEGACY_STYLE_SLUGS, keep=imported_slugs)
    _apply_default_style(DEFAULT_STYLE_SLUG)
    db.session.commit()
    print(f"  Styles: {len(style_map)} imported; default='{DEFAULT_STYLE_SLUG}'")

    # Ensure every seeded style carries the edge-alignment block so a fresh
    # seed renders with header nav, breadcrumb and content on one vertical
    # line. Idempotent — already-aligned styles are left untouched.
    apply_alignment_to_all_styles(db.session)

    print("\n── Widgets ─────────────────────────────────────────────────────")
    widget_map: dict[str, "CmsWidget"] = {}

    # Menu widgets
    FOOTER_NAV_CSS = """\
/* Footer nav — always horizontal, never burger */
.cms-widget--footer-nav .cms-burger { display: none !important; }
.cms-widget--footer-nav .cms-menu {
  display: flex !important;
  flex-direction: row !important;
  flex-wrap: wrap;
  position: static !important;
  width: auto !important;
  height: auto !important;
  background: transparent !important;
  padding: 0 !important;
  box-shadow: none !important;
  right: auto !important;
}
.cms-widget--footer-nav .cms-menu__item { border-bottom: none !important; position: static !important; }
.cms-widget--footer-nav .cms-menu__link { padding: 0.25rem 0.75rem; font-size: 0.875rem; opacity: 0.8; }
.cms-widget--footer-nav .cms-menu__link:hover { opacity: 1; }
"""

    header_nav = _get_or_create_widget("header-nav", "Header Navigation", "menu")
    widget_map["header-nav"] = header_nav
    _clear_menu_items(header_nav)
    _add_menu_items(
        header_nav,
        [
            {"label": "Home", "url": "/"},
            {
                "label": "Features",
                "page_slug": "features",
            },
            {
                "label": "Pricing",
                "url": None,
                "children": [
                    {"label": "Embedded Pricing", "page_slug": "pricing-embedded"},
                    {"label": "Native CMS Pricing", "page_slug": "pricing-native"},
                    {"label": "All Plans", "url": "/#pricing"},
                ],
            },
            {"label": "About", "page_slug": "about"},
            {"label": "Software", "url": "/category"},
        ],
    )

    footer_nav = _get_or_create_widget(
        "footer-nav", "Footer Navigation", "menu", source_css=FOOTER_NAV_CSS
    )
    widget_map["footer-nav"] = footer_nav
    if db.session.query(CmsMenuItem).filter_by(widget_id=footer_nav.id).count() == 0:
        _add_menu_items(
            footer_nav,
            [
                {"label": "Privacy Policy", "page_slug": "privacy"},
                {"label": "Terms of Service", "page_slug": "terms"},
                {"label": "Contact", "page_slug": "contact"},
                {"label": "Software", "url": "/category"},
            ],
        )

    # HTML widgets
    widget_map["hero-home1"] = _get_or_create_widget(
        "hero-home1",
        "Hero — Home v1",
        "html",
        content_html=HERO_HOME1_HTML,
    )
    widget_map["hero-home2"] = _get_or_create_widget(
        "hero-home2",
        "Hero — Home v2 Split",
        "html",
        content_html=HERO_HOME2_HTML,
    )
    widget_map["cta-primary"] = _get_or_create_widget(
        "cta-primary",
        "CTA — Get Started",
        "html",
        content_html=CTA_PRIMARY_HTML,
    )
    widget_map["features-3col"] = _get_or_create_widget(
        "features-3col",
        "Features — 3 Columns",
        "html",
        content_html=FEATURES_3COL_HTML,
    )
    widget_map["pricing-2col"] = _get_or_create_widget(
        "pricing-2col",
        "Pricing — 2 Plans",
        "html",
        content_html=PRICING_2COL_HTML,
    )
    widget_map["testimonials"] = _get_or_create_widget(
        "testimonials",
        "Testimonials",
        "html",
        content_html=TESTIMONIALS_HTML,
    )
    widget_map["tarif-plans-root"] = _get_or_create_widget(
        "tarif-plans-root",
        "Tarif Plans — Root (all plans)",
        "html",
        content_html=TARIF_PLANS_ROOT_HTML,
    )
    widget_map["tarif-plans-backend"] = _get_or_create_widget(
        "tarif-plans-backend",
        "Tarif Plans — Backend plugins",
        "html",
        content_html=TARIF_PLANS_BACKEND_HTML,
    )
    widget_map["features-slideshow"] = _get_or_create_widget(
        "features-slideshow",
        "Features — Slideshow",
        "html",
        content_html=FEATURES_SLIDESHOW_HTML,
    )
    widget_map["pricing-embed-demo"] = _get_or_create_widget(
        "pricing-embed-demo",
        "Pricing — Embedded Widget Guide",
        "html",
        content_html=PRICING_EMBED_GUIDE_HTML,
    )
    widget_map["pricing-native-plans"] = _get_or_create_widget(
        "pricing-native-plans",
        "Pricing — Native CMS Plans",
        "vue-component",
        content_json={"component": "NativePricingPlans"},
        config=NATIVE_PRICING_CONFIG,
    )
    widget_map["breadcrumbs"] = _get_or_create_widget(
        "breadcrumbs",
        "Breadcrumbs",
        "vue-component",
        content_json={"component": "CmsBreadcrumb"},
        config=BREADCRUMBS_CONFIG,
    )
    widget_map["contact-form"] = _get_or_create_widget(
        "contact-form",
        "Contact Form",
        "vue-component",
        content_json={"component": "ContactForm"},
        config=CONTACT_FORM_CONFIG,
    )
    widget_map["ghrm-categories"] = _get_or_create_widget(
        "ghrm-categories",
        "GHRM Categories",
        "vue-component",
        content_json={"component": "GhrmCatalogueContent", "items_per_page": 12},
    )
    widget_map["ghrm-software-detail"] = _get_or_create_widget(
        "ghrm-software-detail",
        "GHRM Software Detail",
        "vue-component",
        content_json={"component": "GhrmPackageDetail", "items_per_page": 12},
    )
    widget_map["tag-archive"] = _get_or_create_widget(
        "tag-archive",
        "Tag Archive",
        "vue-component",
        content_json={"component": "TagArchive"},
        config={"type": "post", "term_type": "tag", "mode": "excerpt"},
    )
    # Posts archive (blog index) widget — lists ALL published posts (no term
    # filter) via GET /cms/posts?type=post. Placed on the posts-archive layout.
    widget_map[POSTS_ARCHIVE_WIDGET_SLUG] = _get_or_create_widget(
        POSTS_ARCHIVE_WIDGET_SLUG,
        "Posts Archive (Blog Index)",
        "vue-component",
        content_json={"component": "PostArchive", "mode": "category", "type": "post"},
        config={
            "component_name": "PostArchive",
            "type": "post",
            "mode": "category",
            "posts_per_page": 20,
            "paginate": True,
        },
    )
    # Shared term-archive widget — lists a category's OR a tag's posts. Reads the
    # term type + slug from the catch-all route (NOT config), so ONE widget on the
    # ONE terms-archive layout renders every category and tag archive.
    widget_map[TERMS_ARCHIVE_WIDGET_SLUG] = _get_or_create_widget(
        TERMS_ARCHIVE_WIDGET_SLUG,
        TERMS_ARCHIVE_WIDGET_NAME,
        "vue-component",
        content_json=dict(TERMS_ARCHIVE_WIDGET_CONTENT_JSON),
        config=dict(TERMS_ARCHIVE_WIDGET_CONFIG),
    )
    widget_map["addon-catalog"] = _get_or_create_widget(
        "addon-catalog",
        "Addon Catalog",
        "vue-component",
        content_json={"component": "AddonCatalog"},
    )

    # Standalone vue-component widgets (CustomCode / Category / Search /
    # SearchResults) — seeded so they appear in the admin widget picker.
    for standalone in _STANDALONE_VUE_WIDGETS:
        widget_map[standalone["slug"]] = _get_or_create_widget(
            standalone["slug"],
            standalone["name"],
            standalone["widget_type"],
            content_json=standalone["content_json"],
            config=standalone.get("config"),
        )

    db.session.commit()
    print(f"  Widgets: {len(widget_map)} total")

    print("\n── Layouts ─────────────────────────────────────────────────────")
    layout_map: dict[str, "CmsLayout"] = {}
    for ld in LAYOUTS:
        layout_slug = cast(str, ld["slug"])
        layout_map[layout_slug] = _get_or_create_layout(ld, widget_map)
    db.session.commit()
    print(f"  Layouts: {len(layout_map)} total")

    # Unified content layer (cms_post / cms_term) — the single source of truth.
    # Pages, categories and page-widget assignments are seeded straight through
    # the unified services (the legacy cms_page round-trip was retired in S105).
    (
        post_service,
        term_service,
        post_repo,
        term_repo,
        post_widget_repo,
    ) = _build_unified_services()

    print("\n── Categories (cms_term) ───────────────────────────────────────")
    for cat_slug, cat_name in (
        ("about", "About"),
        ("blog", "Blog"),
        ("static-pages", "Static Pages"),
        ("ghrm", "Software Catalogue"),
    ):
        _get_or_create_category_term(term_service, term_repo, cat_slug, cat_name)
    db.session.commit()

    print("\n── Pages (cms_post type=page) ──────────────────────────────────")
    pages_data = _load_pages()
    page_map: dict[str, dict] = {}
    for pd in pages_data:
        page_layout_slug = cast(Optional[str], pd.get("layout_slug"))
        layout_obj = layout_map.get(page_layout_slug) if page_layout_slug else None
        page_style_slug = cast(Optional[str], pd.get("style_slug"))
        style_obj = style_map.get(page_style_slug) if page_style_slug else None
        post = _get_or_create_unified_page(
            post_service,
            post_repo,
            pd["slug"],
            pd["name"],
            layout_obj,
            style_obj,
            content_json=pd.get("content_json"),
            content_html=pd.get("content_html"),
            meta_description=pd.get("meta_description"),
            sort_order=pd.get("sort_order", 0),
            robots=pd.get("robots", "index,follow"),
            is_published=pd.get("is_published", True),
        )
        if post:
            page_map[pd["slug"]] = post
    db.session.commit()

    print("\n── Page Widgets (cms_post_widget) ──────────────────────────────")
    for pd in pages_data:
        assignments = pd.get("page_widget_assignments", [])
        post_for_assign = page_map.get(pd["slug"])
        if assignments and post_for_assign:
            _set_unified_page_widgets(
                post_widget_repo, post_for_assign, assignments, widget_map
            )
    db.session.commit()

    print("\n── Docs page re-point (S121) ───────────────────────────────────")
    _repoint_docs_page_to_docs_layout(
        post_repo, post_widget_repo, layout_map, widget_map
    )
    db.session.commit()

    print("\n── Posts archive page (blog index) ─────────────────────────────")
    _seed_posts_archive_page(post_service, post_repo, layout_map)
    db.session.commit()

    print("\n── Routing Rules ───────────────────────────────────────────────")
    _seed_home_routing_rules()

    print("\n── Unified demo content (cms_post / cms_term) ──────────────────")
    _seed_unified_demo_content(post_service, term_service)

    print("\n" + "=" * 55)
    print("✓ CMS demo data population complete")
    print(f"  Styles      : {len(STYLES)}")
    print(
        f"  Widgets     : {len(widget_map)} (incl. breadcrumbs, contact-form, ghrm-* vue-components)"
    )
    print(f"  Layouts     : {len(LAYOUTS)}")
    print("  Categories  : about, blog, static-pages, ghrm")
    print(
        "  Pages       : 19 (index [home], home2, landing2, landing3, about, privacy,"
    )
    print(
        "                    terms, contact, features, pricing-embedded, pricing-native,"
    )
    print("                    we-are-launching-soon, ghrm-software-catalogue,")
    print(
        "                    ghrm-software-detail, software, category, category/backend,"
    )
    print("                    category/fe-user, category/fe-admin)")
    print("  Routing     : /index → / (301), /home → / (301)")
    print("  Header nav  : Home | Features | Pricing (submenu) | About | Software")
    print("=" * 55)


if __name__ == "__main__":
    from vbwd.app import create_app

    app = create_app()
    with app.app_context():
        populate_cms()
