# CMS Import / Export — developer guide

How the **cms** plugin participates in the platform's Unified Data Exchange (S46) and the older bespoke CMS bulk routes — usage, CLI, the per-entity exchangers, and how to add a new one. For the generic seam + the `EntityExchanger` contract see `vbwd-backend/docs/developer/import-export.md`.

## Two ways CMS content moves — and how they relate

1. **Generic data-exchange (S46.5)** — six `EntityExchanger`s registered into the core `data_exchange_registry` at `CmsPlugin.on_enable`. CMS entities show up on **Settings → Import/Export** (General tab, "Content" cluster), in the **per-list controls**, and in the **`flask data-exchange` CLI** — uniform with every other entity.
2. **Bespoke posts routes (retained for content ingestion)** — `GET /api/v1/admin/cms/posts/export` / `POST .../posts/import` (VBWD-standard post JSON). These are kept because the marketing content-ingestion scripts (`docs/marketing/cms-imports/bin/import.sh`, `restore-home.sh`) drive them programmatically. They share the **same underlying service** (`post_import_export_service`) as the `cms_posts` exchanger, so there is one serialization code path. **All other bespoke CMS export/import routes (pages, images, layouts, widgets, styles, terms, and the full-CMS ZIP) have been retired** — use the unified data-exchange framework instead.

## The six CMS exchangers

Defined in `plugins/cms/src/services/data_exchange/cms_exchangers.py`, all cluster **`content`**, registered by `register_cms_exchangers(db.session, file_storage=…)`:

| entity_key | model / source | natural key | formats | notes |
|---|---|---|---|---|
| `cms_posts` | `cms_post` via `PostImportExportService` | `slug` | json | **carries S55 `content_blocks` + `page_assignments`** (widget refs by slug; unknown slugs skipped) |
| `cms_terms` | `cms_term` via `TermImportExportService` | `slug` | json | categories + tags |
| `cms_layouts` | `cms_layout` (BaseModelExchanger) | `slug` | json | |
| `cms_styles` | `cms_style` (BaseModelExchanger) | `slug` | json | |
| `cms_widgets` | `cms_widget` (BaseModelExchanger) | `slug` | json | |
| `cms_images` | `cms_image` (custom) | `slug` | json, zip | **binary** emitted base64 in JSON / as `assets/` in a ZIP bundle; written back via the gallery `IFileStorage` |

Permissions are **reused, not minted** — each exchanger overrides `export_permission` / `import_permission` to the existing CMS perms:
`cms_posts` → `cms.pages.view` / `cms.pages.manage`; `cms_images` → `cms.images.*`; `cms_widgets` → `cms.widgets.*`; `cms_layouts` → `cms.layouts.manage`; `cms_styles` → `cms.styles.manage`. Superadmin bypasses.

## Usage — UI

- **Settings → Import / Export** (last item in the SETTINGS sidebar group): the CMS entities appear under the **Content** cluster. Export per-entity (json; images also zip), or include them in a multi-entity ZIP bundle. Import a `.json`/`.zip` with a mode (`upsert` default; `replace_all` superadmin-only) and an optional **Dry-run** preview.
- **Per-list controls** also appear on CMS list pages where wired (Export selected/all/filter + Import).
- **Posts content ingestion** — `GET/POST /api/v1/admin/cms/posts/{export,import}` drive the marketing content-pack scripts and the posts list page.

## Usage — CLI

```bash
# discover keys
flask data-exchange list | grep cms_

# export all pages/posts (carries content_blocks + page_assignments)
flask data-exchange export cms_posts --all -o posts.json

# export the term taxonomy
flask data-exchange export cms_terms --all -o terms.json

# import posts (preview first, then for real)
flask data-exchange import cms_posts posts.json --mode upsert --dry-run
flask data-exchange import cms_posts posts.json --mode upsert

# images round-trip the binary (base64 in the json envelope)
flask data-exchange export cms_images --all -o images.json
```

A typical cross-instance content migration: export `cms_terms`, `cms_layouts`, `cms_styles`, `cms_widgets`, `cms_images`, then `cms_posts` (posts reference terms/layouts/widgets by slug, so import the referents first; unresolved refs are reported in `errors[]`, not fatal).

## `cms_posts` — the content_blocks / page_assignments detail

`CmsPostsExchanger` delegates to `PostImportExportService` (not `BaseModelExchanger`) so the per-row shape is produced in one place and matches the bespoke `/admin/cms/posts/*` routes byte-for-byte. The service was extended (S46.5) to accept optional `content_block_repo` / `post_widget_repo` / `widget_repo`; when wired it emits and round-trips:
- **`content_blocks`** — the S55 per-area content blocks for the post.
- **`page_assignments`** — the per-post widget assignments, with widget references serialised by **slug** (an unknown widget slug on import is skipped, not fatal).

When those repos are absent the envelope is the lean post shape (back-compat preserved). The bespoke `/admin/cms/posts/*` route factory wires the same repos, so both paths emit identical output.

## `cms_images` — binaries

`CmsImagesExchanger` is custom: export reads each image's bytes and emits them **base64** inside the JSON envelope (so a plain `cms_images.json` is self-contained) and, inside a ZIP bundle, as files under `assets/`. Import decodes and writes back through the gallery `IFileStorage` (the same storage the upload flow uses). This is the template to copy for any binary-bearing entity.

## Adding a new CMS exchanger

1. In `cms_exchangers.py`, either add a `BaseModelExchanger` (flat model — see `cms_layouts`/`cms_styles`/`cms_widgets`) or a custom `EntityExchanger` subclass (nested/binary/delegating — see `cms_posts`/`cms_images`). Use the module's `_SessionModelRepository` adapter for the flat case.
2. Set `entity_key` (prefix `cms_`), `cluster = "content"`, `natural_key` (usually `slug`); override `export_permission`/`import_permission` to the relevant `cms.*` perms.
3. Add it to the list returned by `build_cms_exchangers(...)` so `register_cms_exchangers` picks it up — `CmsPlugin.on_enable` already calls that. No other wiring.
4. Tests first (`plugins/cms/tests/`): unit (manifest metadata + delegation) and integration with `db` (round-trip by slug; for binaries, the bytes survive json AND zip).
5. Gate: `bin/pre-commit-check.sh --plugin cms --full` green (+ the core agnosticism/vocabulary oracles).

## Gotchas

- **Sitemap filter state leaks into tests:** the cms config's `sitemap_include_terms`/`exclude_terms` are read live; if your dev `_test` DB has them set (e.g. from manual SEO testing), term-less fixtures get filtered out. The cms integration `conftest.py` forces a no-filter baseline + registers the sitemap provider — keep that in mind when adding SEO-adjacent tests.
- **`replace_all` on cms_images/posts** is destructive (drop-then-import) and superadmin-only via the API; prefer `upsert` for content packs.
- **Order on import:** posts/layouts reference terms/widgets by slug — import referents before posts to avoid `errors[]` entries.
