# CMS Plugin (Backend)

Headless CMS — pages, categories, images, widgets, layouts, styles, routing rules, geo-blocking (country access control), and a contact form submission endpoint.

## Purpose

Provides a full headless CMS for creating and managing static/dynamic content pages, organised into categories, with support for images, reusable widgets, layout templates, global style configuration, URL routing rules, country-level geo-blocking, and a server-side contact form processor.

## Configuration (`plugins/config.json`)

```json
{
  "cms": {
    "uploads_base_path": "/app/uploads",
    "uploads_base_url": "/uploads",
    "max_image_size_mb": 5,
    "allowed_extensions": ["jpg", "jpeg", "png", "gif", "webp", "svg"]
  }
}
```

## API Routes

### Public

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/cms/categories` | List all categories |
| GET | `/api/v1/cms/pages` | List published pages (paginated, filterable by category) |
| GET | `/api/v1/cms/pages/<slug>` | Get page by slug |
| GET | `/api/v1/cms/widgets/by-slug/<slug>` | Get an **active** widget by slug (404 when missing or inactive) |
| GET | `/uploads/<path>` | Serve uploaded files |
| POST | `/api/v1/contact` | Submit a contact form |

### Admin (requires `@require_auth` + `@require_admin`)

#### Pages
| Method | Path | Description |
|--------|------|-------------|
| GET / POST | `/api/v1/admin/cms/pages` | List / create pages |
| GET / PUT / DELETE | `/api/v1/admin/cms/pages/<id>` | Page detail / update / delete |
| POST | `/api/v1/admin/cms/pages/bulk` | Bulk operations |

#### Categories
| Method | Path | Description |
|--------|------|-------------|
| GET / POST | `/api/v1/admin/cms/categories` | List / create categories |
| GET / PUT / DELETE | `/api/v1/admin/cms/categories/<id>` | Category detail / update / delete |

#### Images
| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/admin/cms/images` | List images (paginated) |
| POST | `/api/v1/admin/cms/images/upload` | Upload image |
| PUT | `/api/v1/admin/cms/images/<id>` | Update image metadata |
| POST | `/api/v1/admin/cms/images/<id>/resize` | Resize image |
| DELETE | `/api/v1/admin/cms/images/<id>` | Delete image |
| POST | `/api/v1/admin/cms/images/bulk` | Bulk delete |

#### Widgets
| Method | Path | Description |
|--------|------|-------------|
| GET / POST | `/api/v1/admin/cms/widgets` | List / create widgets |
| GET / PUT / DELETE | `/api/v1/admin/cms/widgets/<id>` | Widget detail / update / delete |
| POST | `/api/v1/admin/cms/widgets/bulk` | Bulk delete |

#### Layouts
| Method | Path | Description |
|--------|------|-------------|
| GET / POST | `/api/v1/admin/cms/layouts` | List / create layouts |
| GET / PUT / DELETE | `/api/v1/admin/cms/layouts/<id>` | Layout detail / update / delete |
| POST | `/api/v1/admin/cms/layouts/bulk` | Bulk delete |

#### Styles
| Method | Path | Description |
|--------|------|-------------|
| GET / POST | `/api/v1/admin/cms/styles` | List / create styles |
| GET / PUT / DELETE | `/api/v1/admin/cms/styles/<id>` | Style detail / update / delete |
| POST | `/api/v1/admin/cms/styles/bulk` | Bulk delete |

#### Routing Rules
| Method | Path | Description |
|--------|------|-------------|
| GET / POST | `/api/v1/admin/cms/routing-rules` | List / create routing rules |
| GET / PUT / DELETE | `/api/v1/admin/cms/routing-rules/<id>` | Rule detail / update / delete |
| POST | `/api/v1/admin/cms/routing-rules/reload` | Force nginx config reload |

#### Geo-Blocking
| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/api/v1/admin/cms/geo-block` | `cms.configure` | Geo-block config + derived allowed-country set |
| PUT | `/api/v1/admin/cms/geo-block` | `cms.configure` | Update config (also republishes the nginx `geo-block.json`) |

> Import / export of CMS content is served by the unified data-exchange
> framework at `/api/v1/admin/data-exchange/*`. The former bespoke CMS
> export/import routes were retired.

---

## Widget Types

| `widget_type` | Description |
|---------------|-------------|
| `html` | Raw HTML/CSS content block |
| `menu` | Navigation menu (header-nav, footer-nav, etc.) |
| `slideshow` | Image slideshow |
| `vue-component` | Client-side Vue component rendered by the frontend (see below) |

### Vue-Component Widgets

`vue-component` widgets delegate rendering to a named Vue component registered in the frontend. The `config` field drives all component behaviour.

#### CmsBreadcrumb

Renders a breadcrumb trail for the current page.

| Config key | Type | Default | Description |
|------------|------|---------|-------------|
| `component_name` | string | `"CmsBreadcrumb"` | Component selector (must match frontend registration) |
| `separator` | string | `"/"` | Separator character between crumbs |
| `root_name` | string | `"Home"` | Label for the root crumb |
| `root_slug` | string | `"/home1"` | Href for the root crumb |
| `show_category` | boolean | `false` | Insert a crumb for the page's CMS category |
| `category_label` | string | `""` | Override label when `show_category` is true |
| `max_label_length` | number | `60` | Truncate page title in the last crumb |
| `css` | string | `""` | Scoped CSS injected into the widget's `<style>` |

#### SuperHeader

A complete site header: logo, navigation, search box and one auth link. Drop it into a layout's `header` area.

The navigation is **not** configured here. `nav_widget_slug` names an existing `menu` widget, which SuperHeader fetches over `GET /api/v1/cms/widgets/by-slug/<slug>` and renders through the normal widget renderer — so the referenced widget keeps its own menu items, submenus and mobile burger drawer. Any menu widget can be swapped in by changing the slug. A referenced widget that is itself a `SuperHeader` is skipped.

The search box reuses the `Search` widget's component, so `quicksearch` behaves identically (backed by `/api/v1/cms/search`). The auth link renders `login_label` → `login_path` for anonymous visitors and `dashboard_label` → `dashboard_path` once a valid `auth_token` is present.

| Config key | Type | Default | Description |
|------------|------|---------|-------------|
| `component_name` | string | `"SuperHeader"` | Component selector |
| `logo_image_url` | string | `""` | Logo image; when empty, `logo_text` is rendered instead |
| `logo_text` | string | `"VBWD"` | Text logo, and the `alt` text when `logo_image_url` is set |
| `logo_link` | string | `"/"` | Href for the logo |
| `nav_widget_slug` | string | `"header-nav"` | Slug of an existing `menu` widget to render as the nav; empty renders no nav |
| `show_search` | boolean | `true` | Render the search box |
| `search_placeholder` | string | `"Search…"` | Placeholder text |
| `search_target_path` | string | `"/search"` | Page the full search submits to |
| `search_scope` | string | `"both"` | `"pages"`, `"posts"` or `"both"` |
| `quicksearch` | boolean | `true` | Show the instant results dropdown |
| `quicksearch_limit` | number | `6` | Maximum dropdown rows (1–20) |
| `show_auth_links` | boolean | `true` | Render the auth link |
| `login_label` | string | `"Login"` | Link text shown to anonymous visitors |
| `login_path` | string | `"/login"` | Href shown to anonymous visitors |
| `dashboard_label` | string | `"Dashboard"` | Link text shown to authenticated visitors |
| `dashboard_path` | string | `"/dashboard"` | Href shown to authenticated visitors |
| `css` | string | `""` | Scoped CSS injected into the widget's `<style>` |

Style hooks: `.cms-super-header`, `.cms-super-header__logo`, `.cms-super-header__nav`, `.cms-super-header__search`, `.cms-super-header__auth`.

#### NativePricingPlans

Renders the platform's live pricing plans fetched from the API.

| Config key | Type | Default | Description |
|------------|------|---------|-------------|
| `component_name` | string | `"NativePricingPlans"` | Component selector |
| `mode` | string | `"category"` | `"category"` (show plans by category) or `"slugs"` (explicit plan list) |
| `category` | string | `"root"` | Plan category slug to display when `mode = "category"` |
| `plan_slugs` | array | `[]` | Explicit plan slugs to display when `mode = "slugs"` |
| `css` | string | `""` | Scoped CSS; three ready-to-use commented style blocks are pre-populated |

#### ContactForm

A fully configurable contact form. Submissions are validated server-side (honeypot, rate limit, field validation) and dispatched as a `contact_form.received` event which the **email plugin** converts into a notification email.

| Config key | Type | Default | Description |
|------------|------|---------|-------------|
| `component_name` | string | `"ContactForm"` | Component selector |
| `recipient_email` | string | `""` | Email address that receives submission notifications |
| `success_message` | string | `"Thank you! Your message has been sent."` | Message shown to the user after a successful submission |
| `fields` | array | see below | Ordered list of form field definitions |
| `rate_limit_enabled` | boolean | `true` | Enable per-IP rate limiting |
| `rate_limit_max` | number | `5` | Max submissions allowed per IP per window |
| `rate_limit_window_minutes` | number | `60` | Rolling window size in minutes |
| `captcha_html` | string | `""` | Raw HTML to inject a CAPTCHA widget (e.g. hCaptcha, reCAPTCHA) |
| `analytics_html` | string | `""` | Raw HTML for pixel/analytics tracking on submission |
| `css` | string | `""` | Scoped CSS for the rendered form |

**Field definition object:**

| Key | Type | Required | Description |
|-----|------|----------|-------------|
| `id` | string | yes | Unique field key (used as the form input `name`) |
| `label` | string | yes | Visible label shown above the input |
| `type` | string | yes | `text`, `email`, `url`, `textarea`, `radio`, `checkbox` |
| `required` | boolean | no | Mark field as mandatory |
| `options` | array of strings | only for `radio`/`checkbox` | Selectable option values |

Built-in fields `name` (text) and `email` (email) are always present and cannot be removed. Additional fields can be added, reordered, and removed via the widget editor.

**Submission flow:**

```
POST /api/v1/contact
  ↓
ContactFormService.process_submission()
  ├── Honeypot check (_hp field must be empty)
  ├── Redis rate limit (key: cf_rl:<widget_slug>:<ip>)
  └── Field validation & sanitization
  ↓
EventBus.emit("contact_form.received", payload)
  ↓
EmailPlugin handler → send notification to recipient_email
```

**Request body:**

```json
{
  "widget_slug": "contact-form",
  "_hp": "",
  "fields": {
    "name": "Alice",
    "email": "alice@example.com",
    "field_1": "Hello!"
  }
}
```

**Success response:** `200 { "message": "Thank you! Your message has been sent." }`

**Error responses:**

| Status | Meaning |
|--------|---------|
| `400` | Validation error (required field missing, bad email, etc.) |
| `429` | Rate limit exceeded |
| `200` | Also returned for honeypot triggers (to avoid exposing bot detection) |

#### CookieConsent (GDPR/DSGVO)

A client-only GDPR/DSGVO **cookie-consent overlay** driving Google Consent Mode v2.
The backend adds **no endpoint and no per-widget logic** — it only seeds the
picker RECORD (`populate_cms._STANDALONE_VUE_WIDGETS`, slug `cookie-consent`); all
state lives client-side in `localStorage`. Settings ride the `CmsWidget.config`
JSON (no model or migration change). An admin drops the widget into any layout
area; it renders as a fixed body overlay, so the area is irrelevant.

| Config key | Type | Default | Description |
|------------|------|---------|-------------|
| `component_name` | string | `"CookieConsent"` | Component selector |
| `consent_version` | number | `1` | Bump to re-prompt every visitor after a policy change |
| `privacy_policy_url` | string | `"/privacy"` | Linked from the dialog (informed consent) |
| `mode` | string | `"modal"` | `modal` (blocking) or `banner` (non-blocking) |
| `categories` | array | `["necessary","statistics","marketing","preferences"]` | Optional buckets shown; `necessary` is always implicit/locked |
| `show_settings_button` | boolean | `true` | Persistent re-open affordance (withdraw consent) |
| `debug_mode` | boolean | `false` | Plugin debug toggle |

**Compliance posture:** strictly-necessary flows (login/cart/checkout) are never
gated — consent gates cookies/scripts via Consent Mode, not routes. Reject is as
prominent as Accept on layer 1; granular per-category control is on layer 2.

---

## CMS Import / Export

Transferring CMS content between environments is handled by the unified
data-exchange framework (`/api/v1/admin/data-exchange/*`), which serialises
CMS entities (pages, widgets, categories, layouts, styles, images, posts,
terms) alongside every other plugin's entities into a single portable archive.
The former bespoke CMS export/import routes have been retired.

---

## Geo-Blocking

Country access control: block visitors whose GeoIP country is not in the allowed
list (derived from core `vbwd_country.is_enabled`), redirect them to a `/locked`
CMS page, with a GET-param → HMAC-signed cookie bypass. Configured from the
**"Blocked countries"** tab at `/admin/cms/routing-rules`; enforced at **two
layers** — the fe-user nginx via an njs handler (the real page-load block) and the
Flask `CmsGeoBlockMiddleware`. Off by default; fail-open on a missing GeoIP DB.
See [`docs/developer/geo-blocking.md`](docs/developer/geo-blocking.md).

---

## Events

| Event | Emitted by | Payload |
|-------|-----------|---------|
| `contact_form.received` | `POST /api/v1/contact` | `{widget_slug, recipient_email, fields, remote_ip}` |

Consumed by the **email plugin** to dispatch notification emails.

---

## Database

| Table | Description |
|-------|-------------|
| `cms_page` | Content pages |
| `cms_category` | Page categories (hierarchical) |
| `cms_image` | Uploaded images (metadata + file path) |
| `cms_widget` | Reusable content blocks |
| `cms_layout` | Layout templates (areas + widget slot assignments) |
| `cms_layout_widget` | M2M: layout areas → widgets |
| `cms_style` | Global CSS style presets |
| `cms_routing_rule` | URL routing/redirect rules |
| `cms_geo_block_config` | Singleton geo-blocking settings (S120) |

Migration: `alembic/versions/20260302_create_cms_tables.py`

---

## Frontend

| App | Location |
|-----|----------|
| Admin | `vbwd-fe-admin/plugins/cms-admin/` |
| User (renderer) | `vbwd-fe-user/plugins/cms/` |

---

## Demo Data

```bash
./plugins/cms/bin/populate-db.sh
```

Seeds 10 styles, widgets (including breadcrumbs, native pricing plans, and contact form), 5 layouts, 3 categories, 12 pages, and a default routing rule.

---

## Testing

```bash
docker compose run --rm test python -m pytest plugins/cms/tests/ -v
```

---

## Related

| | Repository |
|-|------------|
| 👤 Frontend (user) | [vbwd-fe-user-plugin-cms](https://github.com/VBWD-platform/vbwd-fe-user-plugin-cms) |
| 🛠 Frontend (admin) | [vbwd-fe-admin-plugin-cms](https://github.com/VBWD-platform/vbwd-fe-admin-plugin-cms) |

**Core:** [vbwd-backend](https://github.com/VBWD-platform/vbwd-backend)
