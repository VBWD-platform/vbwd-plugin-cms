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

project_root = Path(__file__).parent.parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from src.extensions import db  # noqa: E402
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

    html_clean = re.sub(r"<style[^>]*>(.*?)</style>", _grab, html, flags=re.DOTALL).strip()
    b64 = base64.b64encode(html_clean.encode("utf-8")).decode("ascii")
    return {"content": b64}, "\n\n".join(css_parts)


# ─── Styles ───────────────────────────────────────────────────────────────────

LIGHT_BASE = """
*, *::before, *::after { box-sizing: border-box; }
body { margin: 0; font-family: var(--font-sans, 'Inter', system-ui, sans-serif); font-size: 16px; line-height: 1.6; }
h1, h2, h3, h4, h5, h6 { line-height: 1.25; margin: 0 0 0.75em; font-weight: 700; }
p { margin: 0 0 1em; }
a { color: var(--color-link); text-decoration: none; }
a:hover { text-decoration: underline; }
img { max-width: 100%; height: auto; display: block; }
.container { max-width: 1200px; margin: 0 auto; padding: 0 1.5rem; }
.btn { display: inline-flex; align-items: center; padding: 0.65rem 1.5rem; border-radius: 6px; font-weight: 600; cursor: pointer; border: 2px solid transparent; transition: all 0.15s; }
.btn-primary { background: var(--color-primary); color: #fff; }
.btn-primary:hover { filter: brightness(1.1); }
.btn-outline { background: transparent; border-color: var(--color-primary); color: var(--color-primary); }
section { padding: 4rem 0; }
"""

DARK_BASE = LIGHT_BASE

STYLES = [
    # ── Light themes ──────────────────────────────────────────────────────────
    {
        "slug": "light-clean",
        "name": "Light — Clean",
        "sort_order": 10,
        "source_css": LIGHT_BASE + """
:root {
  --color-primary: #2563eb;
  --color-link: #2563eb;
  --color-bg: #ffffff;
  --color-surface: #f8fafc;
  --color-border: #e2e8f0;
  --color-text: #1e293b;
  --color-muted: #64748b;
}
body { background: var(--color-bg); color: var(--color-text); }
header { background: #fff; border-bottom: 1px solid var(--color-border); padding: 0.75rem 0; }
nav a { color: var(--color-text); font-weight: 500; padding: 0 0.875rem; }
nav a:hover { color: var(--color-primary); text-decoration: none; }
footer { background: var(--color-surface); border-top: 1px solid var(--color-border); padding: 2.5rem 0; color: var(--color-muted); font-size: 0.875rem; }
""",
    },
    {
        "slug": "light-warm",
        "name": "Light — Warm",
        "sort_order": 11,
        "source_css": LIGHT_BASE + """
:root {
  --color-primary: #d97706;
  --color-link: #b45309;
  --color-bg: #fffbf5;
  --color-surface: #fef3c7;
  --color-border: #fde68a;
  --color-text: #292524;
  --color-muted: #78716c;
}
body { background: var(--color-bg); color: var(--color-text); }
header { background: #fff8ed; border-bottom: 1px solid var(--color-border); padding: 0.75rem 0; }
nav a { color: var(--color-text); font-weight: 500; padding: 0 0.875rem; }
nav a:hover { color: var(--color-primary); text-decoration: none; }
h1, h2 { color: #92400e; }
footer { background: #fef3c7; border-top: 1px solid var(--color-border); padding: 2.5rem 0; color: var(--color-muted); font-size: 0.875rem; }
""",
    },
    {
        "slug": "light-cool",
        "name": "Light — Cool",
        "sort_order": 12,
        "source_css": LIGHT_BASE + """
:root {
  --color-primary: #0284c7;
  --color-link: #0369a1;
  --color-bg: #f0f9ff;
  --color-surface: #e0f2fe;
  --color-border: #bae6fd;
  --color-text: #0c4a6e;
  --color-muted: #0369a1;
}
body { background: var(--color-bg); color: var(--color-text); }
header { background: #ffffff; border-bottom: 2px solid var(--color-primary); padding: 0.75rem 0; }
nav a { color: var(--color-text); font-weight: 500; padding: 0 0.875rem; }
nav a:hover { color: var(--color-primary); text-decoration: none; }
footer { background: var(--color-surface); border-top: 1px solid var(--color-border); padding: 2.5rem 0; color: var(--color-muted); font-size: 0.875rem; }
""",
    },
    {
        "slug": "light-soft",
        "name": "Light — Soft Pastel",
        "sort_order": 13,
        "source_css": LIGHT_BASE + """
:root {
  --color-primary: #8b5cf6;
  --color-link: #7c3aed;
  --color-bg: #fdfcff;
  --color-surface: #f5f3ff;
  --color-border: #ddd6fe;
  --color-text: #2e1065;
  --color-muted: #7c3aed;
}
body { background: var(--color-bg); color: var(--color-text); }
header { background: #fff; border-bottom: 1px solid var(--color-border); padding: 0.75rem 0; }
nav a { color: var(--color-text); font-weight: 500; padding: 0 0.875rem; }
nav a:hover { color: var(--color-primary); text-decoration: none; }
h1, h2 { background: linear-gradient(135deg, #7c3aed, #2563eb); -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text; }
footer { background: var(--color-surface); border-top: 1px solid var(--color-border); padding: 2.5rem 0; color: var(--color-muted); font-size: 0.875rem; }
""",
    },
    {
        "slug": "light-paper",
        "name": "Light — Paper",
        "sort_order": 14,
        "source_css": LIGHT_BASE + """
:root {
  --color-primary: #1a1a1a;
  --color-link: #374151;
  --color-bg: #faf7f2;
  --color-surface: #f0ebe0;
  --color-border: #d6c9b0;
  --color-text: #1c1917;
  --color-muted: #6b7280;
}
body { background: var(--color-bg); color: var(--color-text); font-family: 'Georgia', 'Times New Roman', serif; }
h1, h2, h3 { font-family: 'Georgia', serif; }
header { background: var(--color-surface); border-bottom: 2px solid var(--color-text); padding: 0.75rem 0; }
nav a { color: var(--color-text); font-weight: 600; padding: 0 0.875rem; letter-spacing: 0.05em; text-transform: uppercase; font-size: 0.85rem; }
nav a:hover { color: #555; text-decoration: none; border-bottom: 2px solid currentColor; }
.btn-primary { background: var(--color-text); color: #faf7f2; border-radius: 0; }
footer { background: var(--color-surface); border-top: 2px solid var(--color-text); padding: 2.5rem 0; color: var(--color-muted); font-size: 0.875rem; }
""",
    },
    # ── Dark themes ───────────────────────────────────────────────────────────
    {
        "slug": "dark-midnight",
        "name": "Dark — Midnight",
        "sort_order": 20,
        "source_css": DARK_BASE + """
:root {
  --color-primary: #60a5fa;
  --color-link: #93c5fd;
  --color-bg: #0f172a;
  --color-surface: #1e293b;
  --color-border: #334155;
  --color-text: #e2e8f0;
  --color-muted: #94a3b8;
}
body { background: var(--color-bg); color: var(--color-text); }
header { background: #0f172a; border-bottom: 1px solid var(--color-border); padding: 0.75rem 0; }
nav a { color: var(--color-text); font-weight: 500; padding: 0 0.875rem; }
nav a:hover { color: var(--color-primary); text-decoration: none; }
a { color: var(--color-link); }
h1, h2 { color: #f1f5f9; }
.btn-primary { background: var(--color-primary); color: #0f172a; }
footer { background: var(--color-surface); border-top: 1px solid var(--color-border); padding: 2.5rem 0; color: var(--color-muted); font-size: 0.875rem; }
section { border-bottom: 1px solid var(--color-border); }
""",
    },
    {
        "slug": "dark-charcoal",
        "name": "Dark — Charcoal",
        "sort_order": 21,
        "source_css": DARK_BASE + """
:root {
  --color-primary: #f97316;
  --color-link: #fb923c;
  --color-bg: #18181b;
  --color-surface: #27272a;
  --color-border: #3f3f46;
  --color-text: #fafafa;
  --color-muted: #a1a1aa;
}
body { background: var(--color-bg); color: var(--color-text); }
header { background: #111113; border-bottom: 1px solid var(--color-border); padding: 0.75rem 0; }
nav a { color: var(--color-muted); font-weight: 500; padding: 0 0.875rem; }
nav a:hover { color: var(--color-primary); text-decoration: none; }
a { color: var(--color-link); }
h1, h2 { color: #fafafa; }
.btn-primary { background: var(--color-primary); color: #18181b; font-weight: 700; }
footer { background: #111113; border-top: 1px solid var(--color-border); padding: 2.5rem 0; color: var(--color-muted); font-size: 0.875rem; }
""",
    },
    {
        "slug": "dark-forest",
        "name": "Dark — Forest",
        "sort_order": 22,
        "source_css": DARK_BASE + """
:root {
  --color-primary: #4ade80;
  --color-link: #86efac;
  --color-bg: #0a1a0f;
  --color-surface: #132218;
  --color-border: #1a3a22;
  --color-text: #d1fae5;
  --color-muted: #6ee7b7;
}
body { background: var(--color-bg); color: var(--color-text); }
header { background: #0a150e; border-bottom: 1px solid var(--color-border); padding: 0.75rem 0; }
nav a { color: var(--color-muted); font-weight: 500; padding: 0 0.875rem; }
nav a:hover { color: var(--color-primary); text-decoration: none; }
a { color: var(--color-link); }
h1, h2 { color: #f0fdf4; text-shadow: 0 0 20px rgba(74, 222, 128, 0.2); }
.btn-primary { background: var(--color-primary); color: #052e16; font-weight: 700; }
footer { background: var(--color-surface); border-top: 1px solid var(--color-border); padding: 2.5rem 0; color: var(--color-muted); font-size: 0.875rem; }
""",
    },
    {
        "slug": "dark-purple",
        "name": "Dark — Purple",
        "sort_order": 23,
        "source_css": DARK_BASE + """
:root {
  --color-primary: #a78bfa;
  --color-link: #c4b5fd;
  --color-bg: #0d0a1e;
  --color-surface: #1a1433;
  --color-border: #2d2358;
  --color-text: #e9d5ff;
  --color-muted: #a78bfa;
}
body { background: var(--color-bg); color: var(--color-text); }
header { background: #0d0a1e; border-bottom: 1px solid var(--color-border); padding: 0.75rem 0; }
nav a { color: var(--color-muted); font-weight: 500; padding: 0 0.875rem; }
nav a:hover { color: #fff; text-decoration: none; }
a { color: var(--color-link); }
h1, h2 { color: #f5f3ff; }
.btn-primary { background: linear-gradient(135deg, #7c3aed, #2563eb); color: #fff; border: none; }
.btn-primary:hover { filter: brightness(1.15); }
footer { background: var(--color-surface); border-top: 1px solid var(--color-border); padding: 2.5rem 0; color: var(--color-muted); font-size: 0.875rem; }
""",
    },
    {
        "slug": "dark-carbon",
        "name": "Dark — Carbon",
        "sort_order": 24,
        "source_css": DARK_BASE + """
:root {
  --color-primary: #e4e4e7;
  --color-link: #a1a1aa;
  --color-bg: #09090b;
  --color-surface: #141416;
  --color-border: #252528;
  --color-text: #fafafa;
  --color-muted: #71717a;
}
body { background: var(--color-bg); color: var(--color-text); font-family: 'JetBrains Mono', 'Fira Code', monospace; }
header { background: #09090b; border-bottom: 1px solid var(--color-border); padding: 0.75rem 0; }
nav a { color: var(--color-muted); font-weight: 500; padding: 0 0.875rem; letter-spacing: 0.05em; text-transform: uppercase; font-size: 0.8rem; }
nav a:hover { color: #fff; text-decoration: none; }
a { color: var(--color-link); }
h1, h2 { color: #fff; letter-spacing: -0.02em; }
.btn-primary { background: #fafafa; color: #09090b; border-radius: 0; font-family: inherit; font-size: 0.8rem; letter-spacing: 0.1em; text-transform: uppercase; }
footer { background: var(--color-surface); border-top: 1px solid var(--color-border); padding: 2.5rem 0; color: var(--color-muted); font-size: 0.75rem; font-family: inherit; }
""",
    },
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
.badge { display: inline-block; padding: 2px 10px; border-radius: 12px; background: var(--color-primary); color: #fff; font-size: 0.8rem; font-weight: 600; margin-bottom: 1rem; }
.hero-split h1 { font-size: clamp(1.75rem, 3.5vw, 3rem); margin-bottom: 1rem; }
.hero-split p { font-size: 1.1rem; opacity: 0.8; margin-bottom: 2rem; }
.hero-placeholder { font-size: 8rem; text-align: center; line-height: 1; background: var(--color-surface, #f8fafc); border-radius: 16px; padding: 3rem; }
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
.feature-card { padding: 2rem; border-radius: 12px; background: var(--color-surface, #f8fafc); border: 1px solid var(--color-border, #e2e8f0); }
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
        <a href="/signup?plan=pro" class="btn btn-primary" style="width:100%;justify-content:center">Start Free Trial</a>
      </div>
    </div>
  </div>
</section>
<style>
.pricing { padding: 5rem 0; }
.pricing__title { text-align: center; font-size: 2rem; margin-bottom: 3rem; }
.pricing__grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 2rem; max-width: 720px; margin: 0 auto; }
.pricing-card { padding: 2.5rem; border-radius: 12px; background: var(--color-surface, #f8fafc); border: 1px solid var(--color-border, #e2e8f0); }
.pricing-card--featured { border-color: var(--color-primary, #2563eb); box-shadow: 0 0 0 2px var(--color-primary, #2563eb); }
.pricing-card__tier { font-size: 0.85rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.1em; opacity: 0.7; margin-bottom: 0.5rem; }
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
    <p class="features-hero__sub">Everything you need to build, launch, and scale a SaaS product — without months of boilerplate.</p>
  </div>
</section>

<section class="features-slideshow">
  <div class="container">
    <div class="slideshow" id="vbwd-slideshow">
      <div class="slide slide--active">
        <div class="slide__icon">💳</div>
        <h2>Subscription Billing</h2>
        <p>Stripe, PayPal, and YooKassa out of the box. Monthly, annual, and usage-based plans. Automated invoicing and dunning sequences.</p>
      </div>
      <div class="slide">
        <div class="slide__icon">👥</div>
        <h2>User Management</h2>
        <p>Registration, login, roles, profiles, and invitations. JWT-based authentication with refresh tokens and session management.</p>
      </div>
      <div class="slide">
        <div class="slide__icon">🧩</div>
        <h2>Plugin System</h2>
        <p>Extend without touching core. Frontend and backend plugins with lifecycle hooks, dependency resolution, and hot registration.</p>
      </div>
      <div class="slide">
        <div class="slide__icon">📄</div>
        <h2>CMS &amp; Pages</h2>
        <p>Manage layouts, widgets, menus, styles, and content pages from the admin panel. No code changes required for content updates.</p>
      </div>
      <div class="slide">
        <div class="slide__icon">📦</div>
        <h2>Software Catalogue (GHRM)</h2>
        <p>Subscription-gated access to GitHub repositories. Deploy tokens, collaborator management, and automatic version tracking.</p>
      </div>
      <div class="slide">
        <div class="slide__icon">🔌</div>
        <h2>Embeddable Pricing</h2>
        <p>Drop a &lt;script&gt; tag on any page. A responsive pricing table renders inside a sandboxed iframe. Zero framework dependency.</p>
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
.slide { display: none; text-align: center; padding: 2.5rem 2rem; background: var(--color-surface, #f8fafc); border-radius: 16px; border: 1px solid var(--color-border, #e2e8f0); animation: vbwdFadeIn 0.4s ease; }
.slide--active { display: block; }
@keyframes vbwdFadeIn { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: none; } }
.slide__icon { font-size: 3rem; margin-bottom: 1rem; }
.slide h2 { font-size: 1.5rem; margin-bottom: 0.75rem; }
.slide p { opacity: 0.8; font-size: 1rem; max-width: 520px; margin: 0 auto; }
.slideshow-controls { display: flex; align-items: center; justify-content: center; gap: 1rem; margin-top: 1.5rem; }
.slide-btn { background: none; border: 2px solid var(--color-border, #e2e8f0); border-radius: 50%; width: 40px; height: 40px; font-size: 1.4rem; cursor: pointer; color: var(--color-text, #1e293b); transition: all 0.15s; line-height: 1; }
.slide-btn:hover { border-color: var(--color-primary, #2563eb); color: var(--color-primary, #2563eb); }
.slide-dots { display: flex; gap: 6px; }
.slide-dot { width: 8px; height: 8px; border-radius: 50%; border: none; background: var(--color-border, #e2e8f0); cursor: pointer; padding: 0; transition: background 0.2s; }
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
    <p class="embed-hero__sub">Add a fully hosted, responsive pricing table to any page with a single &lt;script&gt; tag. No React, no Vue, no build step required.</p>
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
        <strong>3 — Done.</strong> The widget renders inside a sandboxed iframe. Billing, checkout, and plan management are fully handled by your VBWD backend.
      </li>
    </ol>

    <h2>Configuration Attributes</h2>
    <table class="embed-table">
      <thead>
        <tr><th>Attribute</th><th>Required</th><th>Default</th><th>Description</th></tr>
      </thead>
      <tbody>
        <tr><td><code>data-embed</code></td><td>Yes</td><td>—</td><td>Widget preset. Use <code>landing1</code> for the standard pricing table.</td></tr>
        <tr><td><code>data-category</code></td><td>No</td><td><code>root</code></td><td>Tariff plan category slug. <code>root</code> shows all plans.</td></tr>
        <tr><td><code>data-container</code></td><td>Yes</td><td>—</td><td>ID of the host <code>&lt;div&gt;</code>.</td></tr>
        <tr><td><code>data-locale</code></td><td>No</td><td><code>en</code></td><td>UI language: <code>en</code>, <code>ru</code>, <code>fr</code>, <code>de</code>, …</td></tr>
        <tr><td><code>data-theme</code></td><td>No</td><td><code>light</code></td><td><code>light</code> or <code>dark</code>.</td></tr>
        <tr><td><code>data-height</code></td><td>No</td><td><code>700</code></td><td>iframe height in pixels.</td></tr>
        <tr><td><code>data-plans</code></td><td>No</td><td>all</td><td>Comma-separated plan slugs to display (e.g. <code>starter,pro</code>).</td></tr>
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
.embed-guide h2 { font-size: 1.4rem; margin: 2.5rem 0 1rem; padding-bottom: 0.5rem; border-bottom: 2px solid var(--color-border, #e2e8f0); }
.embed-steps { padding-left: 0; list-style: none; }
.embed-steps li { margin-bottom: 2rem; }
.embed-steps strong { display: block; margin-bottom: 0.5rem; font-size: 1rem; }
pre { background: var(--color-surface, #f8fafc); border: 1px solid var(--color-border, #e2e8f0); border-radius: 8px; padding: 1rem 1.25rem; overflow-x: auto; margin: 0.5rem 0 1rem; }
code { font-family: 'JetBrains Mono', 'Fira Code', 'Courier New', monospace; font-size: 0.875rem; }
.embed-table { width: 100%; border-collapse: collapse; margin: 1rem 0 2rem; font-size: 0.875rem; }
.embed-table th { background: var(--color-surface, #f8fafc); padding: 0.6rem 0.875rem; text-align: left; border: 1px solid var(--color-border, #e2e8f0); font-weight: 600; }
.embed-table td { padding: 0.6rem 0.875rem; border: 1px solid var(--color-border, #e2e8f0); vertical-align: top; }
.embed-table td code, .embed-table th code { background: var(--color-surface, #f8fafc); padding: 2px 5px; border-radius: 3px; font-size: 0.8rem; border: 1px solid var(--color-border, #e2e8f0); }
.embed-live-label { color: var(--color-muted, #64748b); font-size: 0.9rem; margin-bottom: 1rem; }
.embed-live-wrap { border: 2px dashed var(--color-border, #e2e8f0); border-radius: 12px; padding: 1rem; margin-bottom: 2.5rem; min-height: 100px; }
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
        {"id": "name",    "type": "text",     "label": "Name",    "required": True},
        {"id": "email",   "type": "email",    "label": "Email",   "required": True},
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
.testimonial { margin: 0; padding: 2rem; border-radius: 12px; background: var(--color-surface, #f8fafc); border-left: 4px solid var(--color-primary, #2563eb); }
.testimonial p { font-size: 1rem; font-style: italic; margin-bottom: 1rem; opacity: 0.9; }
.testimonial cite { font-size: 0.875rem; opacity: 0.65; font-style: normal; font-weight: 600; }
</style>
"""

STANDARD_CONTENT_HTML = """
<h1>About VBWD</h1>
<p>VBWD is an open-source SaaS platform that gives developers and agencies a production-ready foundation for subscription businesses — without the months of boilerplate. Install it, extend it with plugins, and ship your product.</p>

<h2>What We Build</h2>
<p>VBWD is a full-stack SDK: a Python/Flask backend, a Vue 3 admin panel, and a Vue 3 user-facing frontend. Everything communicates through a clean REST API and is designed to be extended through a plugin system.</p>
<ul>
  <li><strong>Subscription billing</strong> — Stripe, PayPal, and YooKassa ship out of the box</li>
  <li><strong>User management</strong> — registration, login, roles, profiles, invoices</li>
  <li><strong>CMS</strong> — pages, layouts, widgets, styles — all manageable from the admin panel</li>
  <li><strong>Plugin system</strong> — add features without touching core code</li>
</ul>

<h2>Our Philosophy</h2>
<p>We believe the foundation of a SaaS product should be open, auditable, and yours to own. No vendor lock-in, no black boxes. VBWD is released under CC0 — do whatever you want with it.</p>

<h2>Community &amp; Support</h2>
<p>VBWD is built in the open. Contributions, bug reports, and feature requests are welcome on GitHub. For commercial support, managed hosting, and custom plugin development, check our plans below.</p>

<h2>Contact</h2>
<p>Questions? Reach us at <a href="mailto:hello@vbwd.dev">hello@vbwd.dev</a> or open an issue on GitHub.</p>
"""

STANDARD_CONTENT_JSON = {
    "type": "doc",
    "content": [
        {"type": "heading", "attrs": {"level": 1},
         "content": [{"type": "text", "text": "About VBWD"}]},
        {"type": "paragraph",
         "content": [{"type": "text", "text": "VBWD is an open-source SaaS platform that gives developers and agencies a production-ready foundation for subscription businesses — without the months of boilerplate. Install it, extend it with plugins, and ship your product."}]},
        {"type": "heading", "attrs": {"level": 2},
         "content": [{"type": "text", "text": "What We Build"}]},
        {"type": "paragraph",
         "content": [{"type": "text", "text": "VBWD is a full-stack SDK: a Python/Flask backend, a Vue 3 admin panel, and a Vue 3 user-facing frontend. Everything communicates through a clean REST API and is designed to be extended through a plugin system."}]},
        {"type": "bulletList", "content": [
            {"type": "listItem", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Subscription billing — Stripe, PayPal, and YooKassa ship out of the box"}]}]},
            {"type": "listItem", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "User management — registration, login, roles, profiles, invoices"}]}]},
            {"type": "listItem", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "CMS — pages, layouts, widgets, styles — all manageable from the admin panel"}]}]},
            {"type": "listItem", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Plugin system — add features without touching core code"}]}]},
        ]},
        {"type": "heading", "attrs": {"level": 2},
         "content": [{"type": "text", "text": "Our Philosophy"}]},
        {"type": "paragraph",
         "content": [{"type": "text", "text": "We believe the foundation of a SaaS product should be open, auditable, and yours to own. No vendor lock-in, no black boxes. VBWD is released under CC0 — do whatever you want with it."}]},
        {"type": "heading", "attrs": {"level": 2},
         "content": [{"type": "text", "text": "Community & Support"}]},
        {"type": "paragraph",
         "content": [{"type": "text", "text": "VBWD is built in the open. Contributions, bug reports, and feature requests are welcome on GitHub. For commercial support, managed hosting, and custom plugin development, check our plans below."}]},
        {"type": "heading", "attrs": {"level": 2},
         "content": [{"type": "text", "text": "Contact"}]},
        {"type": "paragraph",
         "content": [{"type": "text", "text": "Questions? Reach us at hello@vbwd.dev or open an issue on GitHub."}]},
    ],
}

# ─── Layouts ───────────────────────────────────────────────────────────────────

LAYOUTS = [
    {
        "slug": "contact-form",
        "name": "Contact Form",
        "description": "Page layout with header, content area, contact form widget, and footer.",
        "sort_order": 0,
        "areas": [
            {"name": "header",       "type": "header",  "label": ""},
            {"name": "content",      "type": "content", "label": ""},
            {"name": "contact form", "type": "vue",     "label": ""},
            {"name": "footer",       "type": "footer",  "label": ""},
        ],
        "widget_assignments": [
            ("header",       "header-nav"),
            ("contact form", "contact-form"),
            ("footer",       "footer-nav"),
        ],
    },
    {
        "slug": "ghrm-software-catalogue",
        "name": "GHRM Software Catalogue",
        "description": "GHRM plugin: software catalogue listing with breadcrumbs and category browser.",
        "sort_order": 10,
        "areas": [
            {"name": "header",          "type": "header", "label": "Header"},
            {"name": "breadcrumbs",     "type": "vue",    "label": ""},
            {"name": "ghrm-categories", "type": "vue",    "label": "Categories"},
            {"name": "footer",          "type": "footer", "label": "Footer"},
        ],
        "widget_assignments": [
            ("header",          "header-nav"),
            ("breadcrumbs",     "breadcrumbs"),
            ("ghrm-categories", "ghrm-categories"),
            ("footer",          "footer-nav"),
        ],
    },
    {
        "slug": "ghrm-software-detail",
        "name": "GHRM Software Detail",
        "description": "GHRM plugin: individual software package detail page.",
        "sort_order": 11,
        "areas": [
            {"name": "header",               "type": "header", "label": "Header"},
            {"name": "breadcrumbs",          "type": "vue",    "label": ""},
            {"name": "ghrm-software-detail", "type": "vue",    "label": "Software Detail"},
            {"name": "footer",               "type": "footer", "label": "Footer"},
        ],
        "widget_assignments": [
            ("header",               "header-nav"),
            ("breadcrumbs",          "breadcrumbs"),
            ("ghrm-software-detail", "ghrm-software-detail"),
            ("footer",               "footer-nav"),
        ],
    },
    {
        "slug": "home-v1",
        "name": "Home v1 (Hero + Features + CTA)",
        "description": "Standard homepage with hero, 3-column features, CTA bar, and footer.",
        "sort_order": 10,
        "areas": [
            {"name": "header", "type": "header", "label": "Header Navigation"},
            {"name": "hero", "type": "hero", "label": "Hero Banner"},
            {"name": "features", "type": "three-column", "label": "Feature Highlights"},
            {"name": "cta", "type": "cta-bar", "label": "Call to Action"},
            {"name": "footer", "type": "footer", "label": "Footer"},
        ],
        "widget_assignments": [
            ("header", "header-nav"),
            ("hero", "hero-home1"),
            ("features", "features-3col"),
            ("cta", "cta-primary"),
            ("footer", "footer-nav"),
        ],
    },
    {
        "slug": "home-v2",
        "name": "Home v2 (Split Hero + Pricing + Testimonials)",
        "description": "Modern homepage with split hero, two-column pricing, and testimonials.",
        "sort_order": 11,
        "areas": [
            {"name": "header", "type": "header", "label": "Header Navigation"},
            {"name": "hero", "type": "hero", "label": "Split Hero"},
            {"name": "pricing", "type": "two-column", "label": "Pricing Plans"},
            {"name": "testimonials", "type": "three-column", "label": "Testimonials"},
            {"name": "footer", "type": "footer", "label": "Footer"},
        ],
        "widget_assignments": [
            ("header", "header-nav"),
            ("hero", "hero-home2"),
            ("pricing", "pricing-2col"),
            ("testimonials", "testimonials"),
            ("footer", "footer-nav"),
        ],
    },
    {
        "slug": "landing",
        "name": "Landing Page (Hero + Features + CTA + Testimonials)",
        "description": "Conversion-focused landing layout without content area.",
        "sort_order": 12,
        "areas": [
            {"name": "header", "type": "header", "label": "Header"},
            {"name": "hero", "type": "hero", "label": "Hero"},
            {"name": "features", "type": "three-column", "label": "Features"},
            {"name": "cta", "type": "cta-bar", "label": "CTA"},
            {"name": "social-proof", "type": "three-column", "label": "Testimonials"},
            {"name": "footer", "type": "footer", "label": "Footer"},
        ],
        "widget_assignments": [
            ("header", "header-nav"),
            ("hero", "hero-home1"),
            ("features", "features-3col"),
            ("cta", "cta-primary"),
            ("social-proof", "testimonials"),
            ("footer", "footer-nav"),
        ],
    },
    {
        "slug": "content-page",
        "name": "Content Page (Header + Content + Footer)",
        "description": "Standard article/blog/about page with a content area in the middle.",
        "sort_order": 13,
        "areas": [
            {"name": "header", "type": "header", "label": "Header"},
            {"name": "breadcrumbs", "type": "vue", "label": ""},
            {"name": "main", "type": "content", "label": "Main Content"},
            {"name": "footer", "type": "footer", "label": "Footer"},
        ],
        "widget_assignments": [
            ("header", "header-nav"),
            ("breadcrumbs", "breadcrumbs"),
            ("footer", "footer-nav"),
        ],
    },
    {
        "slug": "native-pricing-page",
        "name": "Native Pricing Page (Header + Vue Component + Footer)",
        "description": "Page layout that renders a configurable Vue pricing component in the main area.",
        "sort_order": 14,
        "areas": [
            {"name": "header", "type": "header", "label": "Header"},
            {"name": "main", "type": "vue-component", "label": "Pricing Component"},
            {"name": "footer", "type": "footer", "label": "Footer"},
        ],
        "widget_assignments": [
            ("header", "header-nav"),
            ("main", "pricing-native-plans"),
            ("footer", "footer-nav"),
        ],
    },
]


# ─── Main ──────────────────────────────────────────────────────────────────────

def _get_or_create_style(slug: str, data: dict) -> "CmsStyle":
    existing = db.session.query(CmsStyle).filter_by(slug=slug).first()
    if existing:
        existing.name = data["name"]
        existing.source_css = data["source_css"]
        existing.sort_order = data.get("sort_order", 0)
        db.session.flush()
        print(f"  ~ style '{slug}' (updated)")
        return existing
    obj = CmsStyle(
        slug=slug,
        name=data["name"],
        source_css=data["source_css"],
        sort_order=data.get("sort_order", 0),
        is_active=True,
    )
    db.session.add(obj)
    db.session.flush()
    print(f"  + style '{slug}'")
    return obj


def _get_or_create_widget(slug: str, name: str, widget_type: str,
                           content_html: str = None,
                           content_json: dict = None,
                           source_css: str = None,
                           config: dict = None) -> "CmsWidget":
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
    for order, (area_name, widget_slug) in enumerate(data.get("widget_assignments", [])):
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


def _get_or_create_page(slug: str, name: str, layout: "CmsLayout",
                          style: "CmsStyle", content_json: dict = None,
                          content_html: str = None,
                          meta_description: str = None,
                          sort_order: int = 0,
                          category_id: str = None,
                          robots: str = "index,follow",
                          is_published: bool = True) -> None:
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
        return
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
    print(f"  + page '{slug}' (layout={layout.slug if layout else None})")


def populate_cms() -> None:
    print("\n── Styles ──────────────────────────────────────────────────────")
    style_map: dict[str, "CmsStyle"] = {}
    for s in STYLES:
        style_map[s["slug"]] = _get_or_create_style(s["slug"], s)
    db.session.commit()
    print(f"  Styles: {len(style_map)} total")

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
    _add_menu_items(header_nav, [
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
    ])

    footer_nav = _get_or_create_widget("footer-nav", "Footer Navigation", "menu",
                                        source_css=FOOTER_NAV_CSS)
    widget_map["footer-nav"] = footer_nav
    if db.session.query(CmsMenuItem).filter_by(widget_id=footer_nav.id).count() == 0:
        _add_menu_items(footer_nav, [
            {"label": "Privacy Policy", "page_slug": "privacy"},
            {"label": "Terms of Service", "page_slug": "terms"},
            {"label": "Contact", "page_slug": "contact"},
            {"label": "Software", "url": "/category"},
        ])

    # HTML widgets
    widget_map["hero-home1"] = _get_or_create_widget(
        "hero-home1", "Hero — Home v1", "html", content_html=HERO_HOME1_HTML,
    )
    widget_map["hero-home2"] = _get_or_create_widget(
        "hero-home2", "Hero — Home v2 Split", "html", content_html=HERO_HOME2_HTML,
    )
    widget_map["cta-primary"] = _get_or_create_widget(
        "cta-primary", "CTA — Get Started", "html", content_html=CTA_PRIMARY_HTML,
    )
    widget_map["features-3col"] = _get_or_create_widget(
        "features-3col", "Features — 3 Columns", "html", content_html=FEATURES_3COL_HTML,
    )
    widget_map["pricing-2col"] = _get_or_create_widget(
        "pricing-2col", "Pricing — 2 Plans", "html", content_html=PRICING_2COL_HTML,
    )
    widget_map["testimonials"] = _get_or_create_widget(
        "testimonials", "Testimonials", "html", content_html=TESTIMONIALS_HTML,
    )
    widget_map["tarif-plans-root"] = _get_or_create_widget(
        "tarif-plans-root", "Tarif Plans — Root (all plans)", "html",
        content_html=TARIF_PLANS_ROOT_HTML,
    )
    widget_map["tarif-plans-backend"] = _get_or_create_widget(
        "tarif-plans-backend", "Tarif Plans — Backend plugins", "html",
        content_html=TARIF_PLANS_BACKEND_HTML,
    )
    widget_map["features-slideshow"] = _get_or_create_widget(
        "features-slideshow", "Features — Slideshow", "html",
        content_html=FEATURES_SLIDESHOW_HTML,
    )
    widget_map["pricing-embed-demo"] = _get_or_create_widget(
        "pricing-embed-demo", "Pricing — Embedded Widget Guide", "html",
        content_html=PRICING_EMBED_GUIDE_HTML,
    )
    widget_map["pricing-native-plans"] = _get_or_create_widget(
        "pricing-native-plans", "Pricing — Native CMS Plans", "vue-component",
        content_json={"component": "NativePricingPlans"},
        config=NATIVE_PRICING_CONFIG,
    )
    widget_map["breadcrumbs"] = _get_or_create_widget(
        "breadcrumbs", "Breadcrumbs", "vue-component",
        content_json={"component": "CmsBreadcrumb"},
        config=BREADCRUMBS_CONFIG,
    )
    widget_map["contact-form"] = _get_or_create_widget(
        "contact-form", "Contact Form", "vue-component",
        content_json={"component": "ContactForm"},
        config=CONTACT_FORM_CONFIG,
    )
    widget_map["ghrm-categories"] = _get_or_create_widget(
        "ghrm-categories", "GHRM Categories", "vue-component",
        content_json={"component": "GhrmCatalogueContent", "items_per_page": 12},
    )
    widget_map["ghrm-software-detail"] = _get_or_create_widget(
        "ghrm-software-detail", "GHRM Software Detail", "vue-component",
        content_json={"component": "GhrmPackageDetail", "items_per_page": 12},
    )

    db.session.commit()
    print(f"  Widgets: {len(widget_map)} total")

    print("\n── Layouts ─────────────────────────────────────────────────────")
    layout_map: dict[str, "CmsLayout"] = {}
    for ld in LAYOUTS:
        layout_map[ld["slug"]] = _get_or_create_layout(ld, widget_map)
    db.session.commit()
    print(f"  Layouts: {len(layout_map)} total")

    print("\n── Categories ──────────────────────────────────────────────────")
    cat_about, _ = _get_or_create_category("about", "About", sort_order=0)
    cat_blog, _ = _get_or_create_category("blog", "Blog", sort_order=0)
    cat_static, _ = _get_or_create_category("static-pages", "Static Pages", sort_order=0)
    cat_ghrm, _ = _get_or_create_category("ghrm", "Software Catalogue", sort_order=0)
    db.session.commit()

    print("\n── Pages ───────────────────────────────────────────────────────")
    default_light = style_map.get("light-clean")
    default_dark = style_map.get("dark-midnight")
    home_v1 = layout_map.get("home-v1")
    home_v2 = layout_map.get("home-v2")
    landing = layout_map.get("landing")
    content_page = layout_map.get("content-page")
    contact_form_layout = layout_map.get("contact-form")
    ghrm_catalogue_layout = layout_map.get("ghrm-software-catalogue")
    ghrm_detail_layout = layout_map.get("ghrm-software-detail")

    _get_or_create_page(
        "home1", "Home — Version 1", home_v1, default_light,
        meta_description="Welcome to our platform. Build something amazing today.",
        sort_order=10,
    )
    _get_or_create_page(
        "home2", "Home — Version 2", home_v2, default_dark,
        meta_description="Smarter workflows, faster results. Try it free.",
        sort_order=11,
    )
    _get_or_create_page(
        "landing2", "Landing Page — Version 2", landing, style_map.get("light-cool"),
        meta_description="Discover why 10,000+ teams choose our platform.",
        sort_order=12,
    )
    _get_or_create_page(
        "landing3", "Landing Page — Version 3", landing, style_map.get("dark-purple"),
        meta_description="The developer platform built for speed and scale.",
        sort_order=13,
    )
    _get_or_create_page(
        "about", "About Us", content_page, default_light,
        content_json=STANDARD_CONTENT_JSON,
        content_html=STANDARD_CONTENT_HTML,
        meta_description="Learn about our team, our story, and our values.",
        sort_order=20,
        category_id=cat_about.id,
    )
    _get_or_create_page(
        "privacy", "Privacy Policy", content_page, default_light,
        content_html="<h1>Privacy Policy</h1><p>Your privacy policy content goes here.</p>",
        meta_description="Read our privacy policy.",
        sort_order=30,
        category_id=cat_about.id,
    )
    _get_or_create_page(
        "terms", "Terms of Service", content_page, default_light,
        content_html="<h1>Terms of Service</h1><p>Your terms of service content goes here.</p>",
        meta_description="Read our terms of service.",
        sort_order=31,
        category_id=cat_about.id,
    )
    _get_or_create_page(
        "contact", "Contact", contact_form_layout, default_light,
        content_json={"type": "doc", "content": [
            {"type": "heading", "attrs": {"level": 1}, "content": [{"type": "text", "text": "Contact Us"}]},
            {"type": "paragraph", "content": [{"type": "text", "text": "Get in touch with our team. We will answer you shortly"}]},
        ]},
        meta_description="Contact our team.",
        sort_order=32,
        category_id=cat_about.id,
    )

    native_pricing_layout = layout_map.get("native-pricing-page")
    _get_or_create_page(
        "features", "Features", content_page, default_light,
        content_html=FEATURES_SLIDESHOW_HTML,
        meta_description="Explore the key features of the VBWD platform: billing, user management, plugins, CMS, and more.",
        sort_order=40,
        category_id=cat_about.id,
    )
    _get_or_create_page(
        "pricing-embedded", "Embedded Pricing Guide", content_page, default_light,
        content_html=PRICING_EMBED_GUIDE_HTML,
        meta_description="Learn how to embed the VBWD pricing widget in any website with a single script tag.",
        sort_order=41,
        category_id=cat_blog.id,
    )
    _get_or_create_page(
        "pricing-native", "Native CMS Pricing", native_pricing_layout, default_light,
        meta_description="View our subscription plans rendered natively within the VBWD CMS.",
        sort_order=42,
    )
    _get_or_create_page(
        "we-are-launching-soon", "We are launching soon!", content_page, default_light,
        content_html="<h1>We are launching soon!</h1><p>Stay tuned for our upcoming launch. Sign up to be notified.</p>",
        meta_description="We are launching soon. Stay tuned.",
        sort_order=50,
        category_id=cat_static.id,
    )

    # ── GHRM pages (Software Catalogue plugin) ──────────────────────────────
    # Template pages (not published) — used as bases by the GHRM plugin
    _get_or_create_page(
        "ghrm-software-catalogue", "GHRM Catalogue Template", ghrm_catalogue_layout, None,
        meta_description="Browse our software catalogue.",
        sort_order=0,
        category_id=cat_ghrm.id,
        robots="noindex,nofollow",
        is_published=False,
    )
    _get_or_create_page(
        "ghrm-software-detail", "GHRM Detail Template", ghrm_detail_layout, None,
        meta_description="Software package details.",
        sort_order=1,
        category_id=cat_ghrm.id,
    )
    # Published catalogue pages
    _get_or_create_page(
        "software", "Software", ghrm_catalogue_layout, default_dark,
        meta_description="Browse all software packages.",
        sort_order=0,
        category_id=cat_ghrm.id,
    )
    _get_or_create_page(
        "category", "Software Catalogue", ghrm_catalogue_layout, default_light,
        meta_description="Browse software packages by category.",
        sort_order=0,
        category_id=cat_ghrm.id,
    )
    _get_or_create_page(
        "category/backend", "Backend Packages", ghrm_catalogue_layout, default_light,
        meta_description="Backend software packages.",
        sort_order=1,
        category_id=cat_ghrm.id,
    )
    _get_or_create_page(
        "category/fe-user", "Fe User Packages", ghrm_catalogue_layout, default_light,
        meta_description="Frontend user packages.",
        sort_order=2,
        category_id=cat_ghrm.id,
    )
    _get_or_create_page(
        "category/fe-admin", "Fe Admin Packages", ghrm_catalogue_layout, default_light,
        meta_description="Frontend admin packages.",
        sort_order=3,
        category_id=cat_ghrm.id,
    )

    db.session.commit()

    print("\n── Routing Rules ───────────────────────────────────────────────")
    rule = db.session.query(CmsRoutingRule).filter_by(match_type="default", layer="middleware").first()
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
    print(f"  Widgets     : {len(widget_map)} (incl. breadcrumbs, contact-form, ghrm-* vue-components)")
    print(f"  Layouts     : {len(LAYOUTS)}")
    print("  Categories  : about, blog, static-pages, ghrm")
    print("  Pages       : 19 (home1, home2, landing2, landing3, about, privacy, terms,")
    print("                    contact, features, pricing-embedded, pricing-native,")
    print("                    we-are-launching-soon, ghrm-software-catalogue,")
    print("                    ghrm-software-detail, software, category, category/backend,")
    print("                    category/fe-user, category/fe-admin)")
    print("  Routing     : default → home1")
    print("  Header nav  : Home | Features | Pricing (submenu) | About | Software")
    print("=" * 55)


if __name__ == "__main__":
    from src.app import create_app

    app = create_app()
    with app.app_context():
        populate_cms()
