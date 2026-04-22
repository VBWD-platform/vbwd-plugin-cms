#!/usr/bin/env python3
"""
Populate the CMS database with demo data.

Creates:
  - 5 light themes + 5 dark themes (CmsStyle)
  - Navigation widgets: header-nav (menu with Pricing submenu), footer-nav (menu)
  - Content widgets: hero-home1, hero-home2, cta-primary, features-3col, features-slideshow,
                     pricing-embed-demo, pricing-native-plans, contact-form (vue-component) (html)
  - 8 layouts: contact-form, ghrm-software-catalogue, ghrm-software-detail,
               home-v1, home-v2, landing, content-page, native-pricing-page
  - 19 pages: home1, home2, landing2, landing3, about, privacy, terms, contact,
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
from pathlib import Path
from typing import Optional, cast

project_root = Path(__file__).parent.parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from vbwd.extensions import db  # noqa: E402
from plugins.cms.src.models.cms_style import CmsStyle  # noqa: E402
from plugins.cms.src.models.cms_widget import CmsWidget  # noqa: E402
from plugins.cms.src.models.cms_menu_item import CmsMenuItem  # noqa: E402
from plugins.cms.src.models.cms_layout import CmsLayout  # noqa: E402
from plugins.cms.src.models.cms_layout_widget import CmsLayoutWidget  # noqa: E402
from plugins.cms.src.models.cms_page import CmsPage  # noqa: E402
from plugins.cms.src.models.cms_category import CmsCategory  # noqa: E402
from plugins.cms.src.models.cms_routing_rule import CmsRoutingRule  # noqa: E402


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

import json as _json
from pathlib import Path as _Path

# Themes are authored as data in docs/imports/theme-styles.json.
# Re-regenerate via docs/imports/_build_theme_styles.py.
_THEMES_PATH = _Path(__file__).resolve().parents[2] / "docs" / "imports" / "theme-styles.json"


def _load_theme_styles() -> tuple[list[dict], str | None]:
    if not _THEMES_PATH.exists():
        print(f"  WARN: theme-styles.json missing at {_THEMES_PATH} — no styles imported")
        return [], None
    doc = _json.loads(_THEMES_PATH.read_text())
    return doc.get("themes", []), doc.get("default_slug")


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
      data-theme="light"
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
  data-theme="light"
  data-height="700"
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
        <tr><td><code>data-theme</code></td><td>No</td><td><code>light</code></td><td><code>light</code> or <code>dark</code>.</td></tr>  # noqa: E501
        <tr><td><code>data-height</code></td><td>No</td><td><code>700</code></td><td>iframe height in pixels.</td></tr>
        <tr><td><code>data-plans</code></td><td>No</td><td>all</td><td>Comma-separated plan slugs to display (e.g. <code>starter,pro</code>).</td></tr>  # noqa: E501
      </tbody>
    </table>

    <h2>Show a Specific Category</h2>
    <pre><code>&lt;script
  src="/embed/widget.js"
  data-embed="landing1"
  data-category="backend"
  data-container="pricing-root"
  data-theme="dark"
&gt;&lt;/script&gt;</code></pre>

    <h2>Filter to 3 Featured Plans</h2>
    <pre><code>&lt;script
  src="/embed/widget.js"
  data-embed="landing1"
  data-category="backend"
  data-plans="starter,pro,enterprise"
  data-container="pricing-root"
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
    "css": NATIVE_PRICING_CSS,
}

BREADCRUMBS_CSS = (
    ".cms-breadcrumb {\n"
    "    display: flex;\n"
    "    align-items: center;\n"
    "    flex-wrap: wrap;\n"
    "    gap: 4px;\n"
    "    font-size: 0.7rem;\n"
    "    color: #6b7280;\n"
    "    padding: 8px 0 0.25rem;\n"
    "}\n"
    ".cms-breadcrumb a, .cms-breadcrumb__link { color: #3498db; text-decoration: none; }\n"
    ".cms-breadcrumb a:hover, .cms-breadcrumb__link:hover { text-decoration: underline; }\n"
    ".cms-breadcrumb__separator { color: #9ca3af; user-select: none; }\n"
    ".cms-breadcrumb__current { color: #374151; font-weight: 500; }"
)

BREADCRUMBS_CONFIG = {
    "component_name": "CmsBreadcrumb",
    "separator": "/",
    "root_name": "Home",
    "root_slug": "/home1",
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

# ─── Layouts ───────────────────────────────────────────────────────────────────

# Layouts are authored as JSON in docs/imports/layouts/ — re-imported on each
# populator run. Edit those files, not this script.
_LAYOUTS_DIR = _THEMES_PATH.parent / "layouts"
_PAGES_DIR   = _THEMES_PATH.parent / "pages"


def _load_layouts() -> list[dict]:
    if not _LAYOUTS_DIR.exists():
        print(f"  WARN: layouts dir missing at {_LAYOUTS_DIR} — no layouts imported")
        return []
    items: list[dict] = []
    for p in sorted(_LAYOUTS_DIR.glob("*.json")):
        items.append(_json.loads(p.read_text()))
    return items


def _load_pages() -> list[dict]:
    if not _PAGES_DIR.exists():
        print(f"  WARN: pages dir missing at {_PAGES_DIR} — no pages imported")
        return []
    items: list[dict] = []
    for p in sorted(_PAGES_DIR.glob("*.json")):
        items.append(_json.loads(p.read_text()))
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


def _get_or_create_category(slug: str, name: str, sort_order: int = 0):
    existing = db.session.query(CmsCategory).filter_by(slug=slug).first()
    if existing:
        existing.name = name
        existing.sort_order = sort_order
        db.session.flush()
        print(f"  ~ category '{slug}' (updated)")
        return existing, False
    obj = CmsCategory(slug=slug, name=name, sort_order=sort_order)
    db.session.add(obj)
    db.session.flush()
    print(f"  + category '{slug}'")
    return obj, True


def _get_or_create_page(
    slug: str,
    name: str,
    layout: Optional["CmsLayout"],
    style: Optional["CmsStyle"],
    content_json: Optional[dict] = None,
    content_html: Optional[str] = None,
    meta_description: Optional[str] = None,
    sort_order: int = 0,
    category_id: Optional[str] = None,
    robots: str = "index,follow",
    is_published: bool = True,
) -> "CmsPage":
    existing = db.session.query(CmsPage).filter_by(slug=slug).first()
    if existing:
        existing.name = name
        existing.layout_id = layout.id if layout else None
        existing.style_id = style.id if style else None
        if content_json is not None:
            existing.content_json = content_json
        if content_html is not None:
            existing.content_html = content_html
        if meta_description:
            existing.meta_description = meta_description
        existing.sort_order = sort_order
        if category_id is not None:
            existing.category_id = category_id
        existing.robots = robots
        db.session.flush()
        print(f"  ~ page '{slug}' (updated)")
        return existing
    page = CmsPage(
        slug=slug,
        name=name,
        language="en",
        content_json=content_json or {"type": "doc", "content": []},
        content_html=content_html,
        is_published=is_published,
        sort_order=sort_order,
        layout_id=layout.id if layout else None,
        style_id=style.id if style else None,
        category_id=category_id,
        use_theme_switcher_styles=False,
        meta_title=name,
        meta_description=meta_description or name,
        robots=robots,
    )
    db.session.add(page)
    db.session.flush()
    print(f"  + page '{slug}' (layout={layout.slug if layout else None})")
    return page


def _set_page_widgets(
    page: "CmsPage",
    assignments: list[tuple[str, str]],
    widget_map: dict[str, "CmsWidget"],
) -> None:
    """Assign page-level widgets. Idempotent — skips if already assigned."""
    from plugins.cms.src.models.cms_page_widget import CmsPageWidget

    existing = db.session.query(CmsPageWidget).filter_by(page_id=page.id).count()
    if existing > 0:
        return
    for order, (area_name, widget_slug) in enumerate(assignments):
        widget = widget_map.get(widget_slug)
        if not widget:
            print(f"    ! widget '{widget_slug}' not found, skipping")
            continue
        pw = CmsPageWidget(
            page_id=page.id,
            widget_id=widget.id,
            area_name=area_name,
            sort_order=order,
        )
        db.session.add(pw)
    db.session.flush()
    print(f"    + {len(assignments)} page widget(s) for '{page.slug}'")


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
            {"label": "Home", "page_slug": "home1"},
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

    db.session.commit()
    print(f"  Widgets: {len(widget_map)} total")

    print("\n── Layouts ─────────────────────────────────────────────────────")
    layout_map: dict[str, "CmsLayout"] = {}
    for ld in LAYOUTS:
        layout_slug = cast(str, ld["slug"])
        layout_map[layout_slug] = _get_or_create_layout(ld, widget_map)
    db.session.commit()
    print(f"  Layouts: {len(layout_map)} total")

    print("\n── Categories ──────────────────────────────────────────────────")
    cat_about, _ = _get_or_create_category("about", "About", sort_order=0)
    cat_blog, _ = _get_or_create_category("blog", "Blog", sort_order=0)
    cat_static, _ = _get_or_create_category(
        "static-pages", "Static Pages", sort_order=0
    )
    cat_ghrm, _ = _get_or_create_category("ghrm", "Software Catalogue", sort_order=0)
    db.session.commit()

    print("\n── Pages ───────────────────────────────────────────────────────")
    pages_data = _load_pages()
    category_by_slug = {
        "about": cat_about, "blog": cat_blog, "static-pages": cat_static, "ghrm": cat_ghrm,
    }
    page_map: dict[str, "CmsPage"] = {}
    for pd in pages_data:
        layout_obj = layout_map.get(pd.get("layout_slug")) if pd.get("layout_slug") else None
        style_obj = style_map.get(pd.get("style_slug")) if pd.get("style_slug") else None
        cat_obj = category_by_slug.get(pd.get("category_slug")) if pd.get("category_slug") else None
        page = _get_or_create_page(
            pd["slug"],
            pd["name"],
            layout_obj,
            style_obj,
            content_json=pd.get("content_json"),
            content_html=pd.get("content_html"),
            meta_description=pd.get("meta_description"),
            sort_order=pd.get("sort_order", 0),
            category_id=(cat_obj.id if cat_obj else None),
            robots=pd.get("robots", "index,follow"),
            is_published=pd.get("is_published", True),
        )
        page_map[pd["slug"]] = page
    db.session.commit()

    print("\n── Page Widgets ────────────────────────────────────────────────")
    for pd in pages_data:
        assignments = [
            (a["area_name"], a["widget_slug"]) for a in pd.get("page_widget_assignments", [])
        ]
        if assignments:
            page = page_map.get(pd["slug"])
            if page:
                _set_page_widgets(page, assignments, widget_map)
    db.session.commit()


    print("\n── Routing Rules ───────────────────────────────────────────────")
    rule = (
        db.session.query(CmsRoutingRule)
        .filter_by(match_type="default", layer="middleware")
        .first()
    )
    if not rule:
        rule = CmsRoutingRule(
            name="home",
            match_type="default",
            target_slug="home1",
            is_active=True,
            priority=0,
            layer="middleware",
            redirect_code=302,
            is_rewrite=False,
        )
        db.session.add(rule)
        db.session.commit()
        print("  + routing rule: default → home1")
    else:
        print(f"  ~ routing rule: default → {rule.target_slug} (exists)")

    print("\n" + "=" * 55)
    print("✓ CMS demo data population complete")
    print(f"  Styles      : {len(STYLES)} (5 light + 5 dark)")
    print(
        f"  Widgets     : {len(widget_map)} (incl. breadcrumbs, contact-form, ghrm-* vue-components)"
    )
    print(f"  Layouts     : {len(LAYOUTS)}")
    print("  Categories  : about, blog, static-pages, ghrm")
    print(
        "  Pages       : 19 (home1, home2, landing2, landing3, about, privacy, terms,"
    )
    print("                    contact, features, pricing-embedded, pricing-native,")
    print("                    we-are-launching-soon, ghrm-software-catalogue,")
    print(
        "                    ghrm-software-detail, software, category, category/backend,"
    )
    print("                    category/fe-user, category/fe-admin)")
    print("  Routing     : default → home1")
    print("  Header nav  : Home | Features | Pricing (submenu) | About | Software")
    print("=" * 55)


if __name__ == "__main__":
    from vbwd.app import create_app

    app = create_app()
    with app.app_context():
        populate_cms()
