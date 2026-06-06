# nginx prerender serving + asset stamping (S47.1 / S47.2 runbook)

This runbook is the single source of truth for how prerendered SEO files are
served and how their build-asset tags are kept fresh across deploys. A reviewer
should be able to reproduce the routing from this document alone.

> **Engineering requirements (BINDING).** TDD-first · DevOps-first · SOLID · DI ·
> DRY · clean code · **core agnostic** · **NO OVERENGINEERING**. The quality gate
> is `bin/pre-commit-check.sh` (`--plugin cms --full` GREEN on every touched
> repo = done; `--quick` while iterating). All backend logic lives in
> `plugins/cms/`; core (`vbwd/`) is untouched. nginx changes live in the
> **source templates only** (`vbwd-fe-user/nginx.{dev,prod}.conf.template`),
> never in a prod instance tree.

---

## 1. Components

| Piece | Where | Role |
|---|---|---|
| Prerender writer | `plugins/cms/src/services/seo_prerender.py` | On `content.changed`, writes/removes `${VAR_DIR}/seo/<slug>.html` (head + body + `__POST__` payload + stamped entry tags). |
| Asset stamper | `plugins/cms/src/services/seo_asset_stamp.py` | Sources the deployed build's hashed entry tags; re-stamps all prerender files on deploy. |
| SPA hand-off util | `vbwd-fe-user/plugins/cms/src/composables/useSeoHandoff.ts` | Reads `#__POST__`; idempotent meta injection keyed by `data-seo="ssr"`. |
| nginx (prod) | `vbwd-fe-user/nginx.prod.conf.template` | Serves the static prerender file to anon/bots; live SPA to logged-in users. |
| nginx (dev) | `vbwd-fe-user/nginx.dev.conf` | Proxies everything to Vite (no static prerender serving in dev). |

---

## 2. The nginx cache-bypass branch (prod)

```nginx
# logged-in users bypass the prerender cache → live CSR SPA (sees unpublished edits)
map $http_cookie $vbwd_is_authed {
    default 0;
    "~*vbwd_session=" 1;
}

location / {
    root /usr/share/nginx/html;
    index index.html;
    if ($vbwd_is_authed) { rewrite ^ /index.html last; }            # cache-bypass
    try_files /seo$uri.html /seo$uri/index.html $uri /index.html;
}
```

- **`map`** reads the request `Cookie` header once and sets `$vbwd_is_authed=1`
  when a `vbwd_session=` cookie is present. It lives at the top level (outside
  `server`), the only place nginx allows a `map`.
- **`if ($vbwd_is_authed)`** rewrites any logged-in request to `/index.html`
  (the CSR shell) → the SPA fetches live data via `/api/`, so an editor sees
  unpublished/draft edits. This is the *only* permitted `if` (a single
  `rewrite ... last`, no side effects — avoids the "if is evil" pitfalls).
- **`try_files`** for anonymous/bot traffic, in order:
  1. `/seo$uri.html` — the prerendered file for a canonical slug
     (`GET /de/pricing` → `/usr/share/nginx/html/seo/de/pricing.html`);
  2. `/seo$uri/index.html` — directory-style canonical slugs;
  3. `$uri` — real files (hashed `/assets/*` js/css, `/favicon.ico`, …);
  4. `/index.html` — SPA fallback (contextual URLs handled client-side, or a
     cold route with no prerender file → the SPA renders it live).

`try_files` is rooted at `root /usr/share/nginx/html`, so `/seo$uri.html`
resolves under `/usr/share/nginx/html/seo/…` — see the mount below.

### Request-flow diagram

```
GET /de/pricing
      │
      ├─ Cookie has vbwd_session=?  ──yes──►  rewrite → /index.html  ──►  live CSR SPA (API data)
      │
      └─ no (anon / Googlebot)
             │
   try_files │ 1) /seo/de/pricing.html        ← prerendered? serve it (full head+body, no Flask, no API)
             │ 2) /seo/de/pricing/index.html
             │ 3) /de/pricing                  ← a real asset?
             │ 4) /index.html                  ← SPA shell fallback
             ▼
   static first paint → browser boots the hashed JS → useSeoHandoff reads
   #__POST__ → mounts the SAME markup → no white flash, no duplicate GET.
```

---

## 3. The `${VAR_DIR}/seo` mount (prod instance compose — NOT edited here)

The backend prerender writer writes to `${VBWD_VAR_DIR}/seo/`. The fe-user nginx
container must see those files **read-only** under its `root`:

```yaml
# prod instance docker-compose (vbwd-demo-instances/instances/<name>/…) — owned
# by the deploy repo; documented here, NOT edited from vbwd-sdk-2.
services:
  fe-user:                       # the nginx container serving the built dist
    volumes:
      - ${VBWD_VAR_DIR}/seo:/usr/share/nginx/html/seo:ro
```

- The backend is the **only writer**; fe-user mounts it **`:ro`** (single source
  of truth, no per-container drift — same discipline as the plugin-state mount).
- **Dev** (`vbwd-fe-user/docker-compose.yaml`) proxies `/` to the Vite dev
  server, so there is **no** static `/seo` serving and **no** mount in dev — the
  prerender→SPA hand-off is a **prod-only serving path**. Editors/devs always get
  the live SPA locally.

---

## 4. Why content changes need NO nginx reload

- **Add a post** → backend writes `${VAR_DIR}/seo/<slug>.html` → `try_files`
  finds it on the next request. No reload, no conf change.
- **Delete / unpublish** → backend removes the file → `try_files` falls through
  to `/index.html`. No reload.
- **`seo.mode=off`** → a backend flag flips `/robots.txt` to `Disallow: /`
  (cms `plugins/cms/src/seo_routes.py`). No nginx edit.

The conf is **static**: it encodes the *routing strategy*, never per-post rules.

---

## 5. Asset stamping & the deploy re-stamp (the D7 invariant)

Each prerendered file embeds the build's **content-hashed** entry tags so the
SPA can boot after the static first paint:

```html
<!--vbwd:assets-->
    <script type="module" src="/assets/index-<hash>.js"></script>
    <link rel="stylesheet" href="/assets/index-<hash>.css" />
<!--/vbwd:assets-->
```

- **At write time** (`seo_prerender.py`): `SeoAssetStamper.current_entry_tags()`
  reads the deployed fe-user build's `index.html` (or a Vite `manifest.json`
  when present) at `VBWD_FE_DIST_DIR` and emits the current tags between the
  `<!--vbwd:assets-->` markers. If the build can't be located it logs and emits
  a safe fallback (`/assets/index.js` + `.css`) — it **never crashes** the
  writer (bots still get a valid head+body).
- **On every frontend deploy** the build hashes change, so a **re-stamp** step
  rewrites just the marker-delimited block in every existing
  `${VAR_DIR}/seo/*.html` (cheap string substitution; the content body is never
  re-rendered). Without it, real users' SPA fails to boot on stale hashes
  (bots stay fine).

### Deploy hook

Run the re-stamp **after** the new fe-user build is in place (so
`VBWD_FE_DIST_DIR` points at the fresh `index.html`/`manifest.json`) and before
serving real traffic. Entry point:

```python
# plugins/cms/src/services/seo_wiring.py
from plugins.cms.src.services.seo_wiring import restamp_prerendered_assets
restamp_prerendered_assets()   # → int (files rewritten)
```

Invoke it from the backend container in the deploy pipeline, e.g.:

```bash
# pseudo deploy step (after FE build is published to VBWD_FE_DIST_DIR)
docker compose exec api python -c \
  "from plugins.cms.src.services.seo_wiring import restamp_prerendered_assets as r; print(r())"
```

> The wiring of this call into `vbwd-demo-instances` CI is a deploy-repo concern
> (config only). This runbook is the contract; the CI job calls the function
> above on each fe-user deploy.

### Config

| Key | Default | Meaning |
|---|---|---|
| `VBWD_FE_DIST_DIR` (env) | _unset_ → fallback tags | Path where the deployed fe-user build (`index.html` / `.vite/manifest.json`) is readable from the backend container. |
| `VBWD_VAR_DIR` (env) | `/app/var` | Root for `${VAR_DIR}/seo/`. |

---

## 6. Site-level snippets in the prerender + static-file CSP (S47.7)

Enabled `head` / `body_open` / `body_close` snippets are baked into each
prerendered file inside per-placement marker blocks — the **same pattern** as the
asset block, so a snippet change re-stamps cheaply without re-rendering content:

```html
<!--vbwd:snippets:head-->
    <script>ga('init')</script>
<!--/vbwd:snippets:head-->
```

- **Re-stamp on change.** A snippet create/update/delete/toggle calls
  `restamp_prerendered_snippets()` (`seo_wiring.py`), which rewrites just the
  snippet blocks across every `${VAR_DIR}/seo/*.html` (idempotent string
  substitution). Snippets are site-wide, so one change invalidates all files.

- **CSP is hash-based, NOT nonce-based — deliberately.** These files are served
  **statically by nginx**, with no Flask per-request response, so a per-request
  CSP **nonce can never match** a static file. The writer therefore bakes a
  **self-contained** `<meta http-equiv="Content-Security-Policy">` into `<head>`
  whose `script-src` lists one `'sha256-…'` per inline snippet body (+ `'self'`),
  with **no `unsafe-inline`**. A hash is stable for a given snippet body — correct
  for a static file (a nonce would require a dynamic response). The CSP meta is
  emitted only when there is at least one inline snippet. The live-CSR /
  logged-in path (dynamic Flask response) may instead receive a Flask-set CSP
  header — that seam is intentionally left for a later increment, not built here.

---

## 6. SPA hand-off + meta dedup (client side)

`vbwd-fe-user/plugins/cms/src/composables/useSeoHandoff.ts`:

- `readSeoHandoff()` parses the inlined `#__POST__` JSON → initial post state, or
  `null` when absent (logged-in / cold route) → the caller falls back to an API
  fetch. (47.3's `PostDetail` consumes this to mount synchronously from the
  payload — no white flash, no redundant `GET /cms/posts/<slug>`.)
- `injectSeoMeta(page)` updates the head **in place** keyed by `data-seo="ssr"`:
  it `querySelector`s the existing server-emitted tag (the prerender writer marks
  every `<meta>`/`<link>` with `data-seo="ssr"`) and **replaces** it instead of
  appending. Empty fields remove stale tags. This is the fix for the old blind
  `appendChild` in `CmsPage.vue`, which duplicated title/canonical/og on every
  navigation. `CmsPage.vue` now calls `injectSeoMeta`.

---

## 7. dev ↔ prod template diff (summary)

| Aspect | dev (`nginx.dev.conf`) | prod (`nginx.prod.conf.template`) |
|---|---|---|
| `location /` | proxy → Vite dev server | static `root` + `try_files` prerender chain |
| `$vbwd_is_authed` map | declared (parity), unused | declared **and** used for cache-bypass |
| `${VAR_DIR}/seo` mount | none (Vite serves) | `:ro` under `/usr/share/nginx/html/seo` |
| Asset hashes | none (Vite, unhashed) | content-hashed → re-stamped on deploy |

---

## 8. Validation

```bash
# nginx syntax (dev)
docker run --rm -v "$PWD/nginx.dev.conf:/etc/nginx/conf.d/default.conf:ro" \
  nginx:alpine nginx -t

# nginx syntax (prod, after rendering the envsubst template)
API_UPSTREAM=backend:5000 PLUGIN_API_UPSTREAM=plugin-api:3001 \
  envsubst '${API_UPSTREAM} ${PLUGIN_API_UPSTREAM}' \
  < nginx.prod.conf.template > /tmp/rendered.conf
docker run --rm -v "/tmp/rendered.conf:/etc/nginx/conf.d/default.conf:ro" \
  nginx:alpine nginx -t
```

### Manual e2e serving proof (47-final — needs a running prod-style stack)

1. **anon** `curl -A Googlebot http://localhost:8080/<slug>` → full `<head>` +
   `content_html`, **no** JS execution / API call for first paint.
2. **logged-in** `curl --cookie 'vbwd_session=…' http://localhost:8080/<slug>` →
   the `index.html` SPA shell (live data via API).
3. **static proof** publish a post → `/seo/<slug>.html` appears and is served
   with **no nginx reload**; delete → file gone, nginx untouched; flip
   `seo.mode=off` → `/robots.txt` becomes `Disallow: /` with no nginx edit.
4. **deploy proof** change the build hash → run `restamp_prerendered_assets()` →
   every `/seo/*.html` entry tag updates → SPA still boots.

---

## 9. Rollback

- **Serving:** revert `nginx.prod.conf.template`'s `location /` to the plain SPA
  fallback (`try_files $uri $uri/ /index.html;`) and drop the `map` — anon users
  then get the live SPA (no prerender). No data migration involved.
- **Mount:** remove the `${VAR_DIR}/seo:…:ro` volume from the prod instance
  compose (deploy repo). The `try_files /seo$uri.html` simply never matches and
  falls through to `/index.html`.
- **Stamping:** if the deploy re-stamp is disabled, anon/bot pages still serve
  fine; only logged-out users on stale prerender files would hit a boot failure
  until the next publish or re-stamp. Re-running `restamp_prerendered_assets()`
  is always safe and idempotent.
