# CMS Page Slug Resolution — Category & Detail Pages

How a frontend URL becomes a rendered CMS page, how **nested** slugs
(`software/mobile`) work, and the pattern plugins (GHRM, docs, shop, …) use to
build "category index → category listing → item detail" hierarchies on top of
plain CMS posts.

This is the CMS-side companion to `plugins/ghrm/docs/catalogue-pages.md`.

---

## One endpoint resolves every public page

```
GET /api/v1/cms/posts/<path:slug>?type=<post_type>&preview_token=<token>
```

`public_get_post()` in `src/routes.py` (registered with the Flask `<path:slug>`
converter, so **the slug may contain slashes**):

```
resolve_published_path(post_type, slug)   # post_type defaults to "page"
  → None                     → 404 {"error": "Post not found"}
  → post, not preview, not publicly visible (e.g. private w/o session) → 404
  → post + matching ?preview_token=        → 200 regardless of status
  → published/public post                  → 200 (areas + terms + custom fields enriched)
```

Key properties:

- **Nested paths** resolve by the **full-path slug**. `software/mobile` is a
  single `cms_post` whose `slug` column is literally `software/mobile` — not a
  parent/child tree walk. To add a category page you create one post with the
  slashed slug.
- **Published** posts are public. **Private** posts need an authorized session.
  Any status is viewable with a valid `?preview_token=` (the editor's Preview
  button).
- A missing post and a not-publicly-visible post both return the **same 404** —
  the client cannot distinguish "never existed" from "exists but hidden".

Do not confuse this with `/api/v1/cms/pages/<slug>` (the older pages API) or the
admin `/api/v1/admin/cms/posts/<post_id>` routes (by UUID, any status,
`@require_admin`).

---

## Frontend: `CmsPage.vue` and the in-app 404

`plugins/cms/src/views/CmsPage.vue` (fe-user) is the universal dispatcher:

1. `store.fetchPage(effectiveSlug, previewToken)` calls the endpoint above.
2. States it renders:
   - `store.loading` → loading text
   - `store.accessDenied` → login / upgrade prompt
   - `store.error || !store.currentPage` → **branded in-app "404 Page not found"**
   - otherwise → the page's type component (see registry below)

The 404 you see in the browser for a bad CMS URL is this **component** state — a
`200 text/html` SPA response, **not** an HTTP 404 and **not** a Vue-Router miss.
That distinction is the fastest way to localize a bug:

| Symptom | Meaning |
|---|---|
| Blank page / router NotFound | No Vue route matched the URL |
| **Branded CMS "404"** (big 404, "Back to home") | Route matched, `CmsPage` mounted, but `GET /cms/posts/<slug>` returned 404 / no post |

---

## The category / detail pattern (how plugins use this)

A plugin that wants `.../:category/:item` URLs registers Vue routes that all
render `CmsPage.vue`, choosing the fetched slug per level. GHRM is the reference
implementation:

| Level | Route path | `CmsPage` slug prop | Posts that must exist |
|---|---|---|---|
| Index | `/software` | `software` | one post `software` |
| Category | `/software/:category_slug` | `software/${category_slug}` | one post **per** category (`software/mobile`, …) |
| Detail | `/software/:category_slug/:package_slug` | `ghrm-software-detail` (**static**) | **one** shared post |

The detail level is the subtle one: **all** items render the **same** CMS post
(`detail_page_slug`). The item identity (`package_slug`) is *not* in the fetched
slug — it stays in the route params and is read by the **widget** embedded in
that page's layout (e.g. `GhrmPackageDetail`), which fetches the item itself.

So a working detail page needs three things aligned:

1. A **route** with the `:item_slug` segment.
2. A **published CMS post** at the static detail slug.
3. A **widget** in that post's layout that reads the route param and loads the item.

Miss #2 (post absent/unpublished, or the configured slug ≠ the seeded slug) and
you get the branded 404 even though the route and widget are fine. This is the
single most common cause of "the listing works but the detail 404s".

---

## Page-type registry (rendering the resolved post)

Once a post loads, `CmsPage.vue` picks the component to render it:

```ts
const type = store.currentPage?.type ?? 'page';
resolveCmsPageType(type) ?? resolveCmsPageType('page') ?? CmsPageTypePage;
```

A plugin registers a custom renderer for its `post.type` from its `index.ts`:

```ts
import { registerCmsPageType } from '<cms>/registry/pageTypeRegistry';
registerCmsPageType('my-type', MyTypeComponent);
```

Default posts (`type: "page"`) render via `CmsPageTypePage.vue`, which lays out
the post's layout areas + widgets. The GHRM catalogue uses the default `page`
type and injects behaviour purely through **widgets**, not a custom page type.

---

## Widgets are the injection seam

A CMS widget that renders a Vue component needs **three** layers to line up
(see the platform memory note "CMS widget = 3 layers"):

1. **fe** — `registerCmsVueComponent('GhrmPackageDetail', Component)` so the CMS
   knows how to render the `vue-component` widget.
2. **fe-admin** — a descriptor in the admin `widgets/index.ts` so editors can
   place it.
3. **DB** — a seeded `cms_widget` row (`widget_type: "vue-component"`,
   `content_json.component: "GhrmPackageDetail"`) assigned into a layout area
   via `cms_layout_widget`.

If a page renders but the plugin content is missing, one of these three is
absent (usually the seeded DB row, or the fe registration in a stale bundle).

---

## Checklist: adding a new category or detail page

- [ ] Create a **published** `cms_post` at the exact slug the frontend fetches
      (index/category: the slashed slug; detail: the static `detail_page_slug`).
- [ ] Seed it through the plugin's `populate_*.py`, never raw SQL.
- [ ] Ensure the post's **layout** has the plugin widget assigned to an area.
- [ ] Verify: `curl -s -o /dev/null -w "%{http_code}" .../api/v1/cms/posts/<slug>`
      returns `200`.
- [ ] If the plugin derives slugs from config, confirm the **runtime** config
      (what `/…/config` reports) matches the **seeded** slug — a mismatch is the
      classic detail-page 404.
