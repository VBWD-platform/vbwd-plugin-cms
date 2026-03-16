# CMS Plugin (Backend)

Headless CMS — pages, categories, images, widgets, layouts, styles, routing rules, and a contact form submission endpoint.

## Purpose

Provides a full headless CMS for creating and managing static/dynamic content pages, organised into categories, with support for images, reusable widgets, layout templates, global style configuration, URL routing rules, and a server-side contact form processor.

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
| GET | `/uploads/<path>` | Serve uploaded files |
| POST | `/api/v1/contact` | Submit a contact form |

### Admin (requires `@require_auth` + `@require_admin`)

#### Pages
| Method | Path | Description |
|--------|------|-------------|
| GET / POST | `/api/v1/admin/cms/pages` | List / create pages |
| GET / PUT / DELETE | `/api/v1/admin/cms/pages/<id>` | Page detail / update / delete |
| POST | `/api/v1/admin/cms/pages/bulk` | Bulk operations |
| POST | `/api/v1/admin/cms/pages/export` | Export pages as JSON |
| POST | `/api/v1/admin/cms/pages/import` | Import pages from JSON |

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
| GET | `/api/v1/admin/cms/images/export` | Export image list as JSON |

#### Widgets
| Method | Path | Description |
|--------|------|-------------|
| GET / POST | `/api/v1/admin/cms/widgets` | List / create widgets |
| GET / PUT / DELETE | `/api/v1/admin/cms/widgets/<id>` | Widget detail / update / delete |
| POST | `/api/v1/admin/cms/widgets/bulk` | Bulk delete |
| POST | `/api/v1/admin/cms/widgets/export` | Export selected widgets as JSON/ZIP |
| POST | `/api/v1/admin/cms/widgets/import` | Import widget from JSON |

#### Layouts
| Method | Path | Description |
|--------|------|-------------|
| GET / POST | `/api/v1/admin/cms/layouts` | List / create layouts |
| GET / PUT / DELETE | `/api/v1/admin/cms/layouts/<id>` | Layout detail / update / delete |
| POST | `/api/v1/admin/cms/layouts/bulk` | Bulk delete |
| POST | `/api/v1/admin/cms/layouts/export` | Export selected layouts |
| POST | `/api/v1/admin/cms/layouts/import` | Import layout from JSON |

#### Styles
| Method | Path | Description |
|--------|------|-------------|
| GET / POST | `/api/v1/admin/cms/styles` | List / create styles |
| GET / PUT / DELETE | `/api/v1/admin/cms/styles/<id>` | Style detail / update / delete |
| POST | `/api/v1/admin/cms/styles/bulk` | Bulk delete |
| POST | `/api/v1/admin/cms/styles/export` | Export selected styles |
| POST | `/api/v1/admin/cms/styles/import` | Import style from JSON |

#### Routing Rules
| Method | Path | Description |
|--------|------|-------------|
| GET / POST | `/api/v1/admin/cms/routing-rules` | List / create routing rules |
| GET / PUT / DELETE | `/api/v1/admin/cms/routing-rules/<id>` | Rule detail / update / delete |
| POST | `/api/v1/admin/cms/routing-rules/reload` | Force nginx config reload |

#### Import / Export (full CMS)
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/v1/admin/cms/export` | Export selected sections as a ZIP archive |
| POST | `/api/v1/admin/cms/import` | Import a ZIP archive with conflict strategy |

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

---

## CMS Import / Export

The full-CMS import/export endpoints allow transferring entire CMS configurations between environments as a ZIP archive.

### Export — `POST /api/v1/admin/cms/export`

**Body:**
```json
{ "sections": ["pages", "widgets", "categories", "layouts", "styles", "routing_rules", "images"] }
```
Pass `["everything"]` to export all sections.

**Response:** `application/zip` binary (`cms-export.zip`)

The ZIP contains:
- `manifest.json` — export metadata (timestamp, version, section list)
- `<section>.json` — array of all records for each section
- `images/<slug>.<ext>` — binary image files (when stored locally)

Pages export includes `category_slug`, `layout_slug`, and `style_slug` fields for FK resolution on import.
Layouts export includes `widget_assignments` (list of `{widget_slug, area_name, sort_order}`) for slot resolution on import.

### Import — `POST /api/v1/admin/cms/import`

**Multipart form fields:**

| Field | Description |
|-------|-------------|
| `file` | The ZIP file |
| `strategy` | `add` \| `index` \| `drop_all` |

**Strategies:**

| Strategy | Behaviour on slug conflict |
|----------|---------------------------|
| `add` | Skip the incoming record — existing record is preserved |
| `index` | Rename the incoming slug to `<slug>-2`, `-3`, … until free |
| `drop_all` | Delete **all** CMS content first, then insert everything from the ZIP |

**Response:**
```json
{
  "imported": {
    "categories": 3,
    "widgets": 8,
    "styles": 5,
    "layouts": 4,
    "pages": 12,
    "routing_rules": 2,
    "images": 6
  },
  "errors": []
}
```

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
