# CMS Geo-Blocking — Developer Guide

Geo-blocking lets an operator **block access to the public CMS site from every country that is not in the allowed list**, redirecting blocked visitors to a `/locked` page — with a GET-param → cookie **bypass** so trusted visitors (including the operator) can still reach the site from a blocked country. It is configured from the **"Blocked countries"** tab at `/admin/cms/routing-rules`, enforced server-side, and survives redeploys (no manual server touch).

It ships **off by default**. A missing GeoIP database or a bad config **never** locks the site out (fail-open, both layers).

---

## Why two layers

Human page loads for the public site are served by the **fe-user nginx**, not Flask. The fe-user nginx serves `location /` from static/prerender; only `/api/`, `/uploads/`, `sitemap`, `robots` proxy to the backend. So a browser opening `/` is **never seen by the Flask middleware** — and those backend routes are in the geo-block passthrough set anyway.

Therefore geo-blocking is enforced at **two independent layers**, with the same decision order and the same fail-open invariant:

| Layer | Sprint | Where | Blocks what |
|---|---|---|---|
| **nginx / njs** | S120.1 | fe-user nginx `location /` (`nginx/geo_block.js`) | **The real block** — human page loads |
| **Flask middleware** | S120 | backend `before_request` (`CmsGeoBlockMiddleware`) | Requests that reach the backend; complements layer 1 (cannot block page loads alone) |

Both layers read the same effective config (the DB singleton + the derived allowed-country set) and mint/verify the **same HMAC bypass token**. Layer 1 reads a JSON descriptor the backend writes on every admin save; layer 2 reads the DB row directly.

```
Admin UI  (fe-admin /admin/cms/routing-rules → "Blocked countries" tab)
  └─► PUT /api/v1/admin/cms/geo-block
        └─► CmsGeoBlockService.update_config()      → cms_geo_block_config (DB singleton)
        └─► GeoBlockNginxWriter.write()             → ${VAR_DIR}/cms/nginx/geo-block.json (atomic)

Browser page load  (GET /)
  └─► fe-user nginx  location / → js_content geo.handle   (nginx/geo_block.js, S120.1)
        ├─ reads /etc/nginx/geo/geo-block.json  (5 s TTL cache)
        ├─ resolves $geoip2_country_code from the mmdb
        └─ pass → @spa  |  302 → /locked  |  Set-Cookie + 302 (bypass grant)

Backend request  (anything reaching Flask)
  └─► GeoIpResolver.before_request()   → g.geoip_country       (S120)
  └─► CmsGeoBlockMiddleware.before_request()
        └─ pass  |  302 → /locked  |  Set-Cookie + 302 (bypass grant)
```

---

## File Structure

```
plugins/cms/src/
├── models/
│   └── cms_geo_block_config.py          # singleton settings model
├── repositories/
│   └── geo_block_config_repository.py   # get-or-create + save
├── services/geo/
│   ├── geoip_resolver.py                # GeoIpResolver (sets g.geoip_country)
│   ├── bypass_token.py                  # GeoBypassTokenSigner (HMAC)
│   ├── geo_block_service.py             # config CRUD + derived allowed set
│   ├── nginx_writer.py                  # GeoBlockNginxWriter → geo-block.json
│   └── geo_block_wiring.py              # DI factories (routes + CLI share these)
├── middleware/
│   └── geo_block_middleware.py          # CmsGeoBlockMiddleware (Flask before_request)
└── cli.py                               # flask cms geo-block sync

vbwd-fe-user/
├── nginx/geo_block.js                          # njs handler (the real block)
├── nginx/docker-entrypoint.d/25-vbwd-geoip2.sh # emits geoip2{} only if mmdb present
├── nginx.prod.conf.template                    # js_import + location / → js_content
└── Dockerfile                                  # compiles GeoIP2 module, loads njs
```

---

## Config — `cms_geo_block_config`

A **singleton** table (one row, get-or-create). Off by default so a fresh deploy never locks anyone out. The allowed-country ISO set is **NOT stored here** — it is derived live from core `vbwd_country.is_enabled`, managed at `/admin/settings/tax-and-countries` (DRY; that screen is the single source).

**File:** `src/models/cms_geo_block_config.py` — extends `BaseModel` (UUID `id`, `created_at`, `updated_at`, `version`).

| Column | Type | Default | Meaning |
|---|---|---|---|
| `is_enabled` | Boolean | `false` | Master switch. Off ⇒ the middleware / njs handler is a pure no-op. |
| `bypass_query` | String(255) | `""` | Normalized `key=value` (e.g. `allowme=yes`). Admin may type `?allowme=yes`/`&allowme=yes`; leading `?`/`&` + whitespace are stripped. Empty ⇒ bypass disabled. |
| `bypass_cookie_ttl_days` | Integer | `30` | Lifetime of the minted bypass cookie (days). |
| `blocked_target_slug` | String(255) | `/locked` | CMS page a blocked visitor is redirected to (build `/locked` as a normal CMS page). Empty ⇒ respond `451` instead of a redirect. |
| `block_unknown_country` | Boolean | `false` | When geo cannot resolve a country (private IP, missing DB): `false` = **fail-open** (pass), `true` = fail-closed (block). Default open so a missing DB never locks the world out. |

> There is **no migration** for the S120.1 nginx path (it sidesteps a pre-existing shared-DB migration blocker). The model + its `20260706_cms_geo_block_config` migration are S120; the middleware fails open if the table is not yet applied.

---

## Admin API

Blueprint `cms_bp`, guarded by `@require_auth @require_admin @require_permission("cms.configure")`.

| Method | Path | Auth | Description |
|---|---|---|---|
| `GET` | `/api/v1/admin/cms/geo-block` | `cms.configure` | Config + derived allowed-country set |
| `PUT` | `/api/v1/admin/cms/geo-block` | `cms.configure` | Validate + persist config, then republish `geo-block.json` |

### GET response

The GET payload adds the read-only allowed-country summary for the tab (`allowed_country_codes` / `allowed_country_count`, derived from core enabled countries):

```json
{
  "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "is_enabled": true,
  "bypass_query": "allowme=yes",
  "bypass_cookie_ttl_days": 30,
  "blocked_target_slug": "/locked",
  "block_unknown_country": false,
  "created_at": "2026-07-06T10:00:00",
  "updated_at": "2026-07-06T10:00:00",
  "allowed_country_codes": ["AT", "CH", "DE"],
  "allowed_country_count": 3
}
```

### PUT request

Send only the fields you want to change. Validation (`CmsGeoBlockService`):

| Field | Constraint |
|---|---|
| `bypass_query` | After normalization, must match `^[^=&?\s]+=[^=&?\s]+$` (a single `key=value`); empty is allowed (bypass off) |
| `bypass_cookie_ttl_days` | Positive integer |
| `blocked_target_slug` | Must start with `/` when non-empty; empty ⇒ `451` |

```json
{
  "is_enabled": true,
  "bypass_query": "allowme=yes",
  "bypass_cookie_ttl_days": 30,
  "blocked_target_slug": "/locked",
  "block_unknown_country": false
}
```

On success the PUT returns the same shape as GET and, as a side effect, calls `GeoBlockNginxWriter.write()` to republish `geo-block.json` (failure to publish is logged, not fatal to the save).

`400` on validation failure or a missing JSON body; `401`/`403` on the auth/permission gate.

---

## Admin UI — "Blocked countries" tab

`/admin/cms/routing-rules` is a tabbed shell: **Rules** (the routing-rule table) and **Blocked countries**. The Blocked-countries tab (`RoutingBlockedCountries.vue` + `stores/geoBlock.ts` in `vbwd-fe-admin`) fields:

- **Enable** — "Block access from all other countries, not in the allowed list." + a live "N countries allowed" count and a link to `/admin/settings/tax-and-countries` (where the allowed list is managed).
- **Bypass query** — e.g. `allowme=yes`.
- **Cookie TTL** — days.
- **Target slug** — default `/locked`.
- **Block unknown country** — toggle.
- **Save** — `PUT /api/v1/admin/cms/geo-block`.

---

## Enforcement layer 1 — nginx / njs (S120.1, the real block)

The njs handler `nginx/geo_block.js` owns the fe-user `location /` via `js_content geo.handle` and returns one of:

- **pass** → `r.internalRedirect('@spa')` — hands off to the unchanged SPA / prerender chain (byte-identical to pre-S120.1);
- **block** → `302 → blocked_target_slug` (or `451` when the slug is empty);
- **grant** → mint a signed bypass cookie and `302` to the clean URL.

Decision order mirrors the middleware: OFF/missing-config → passthrough (static assets by extension + the locked slug and its sub-paths, loop-guard) → bypass GET → bypass cookie → country gate.

### Country resolution

The `geoip2` module resolves `$geoip2_country_code` from the mmdb. Because the `geoip2` directive opens the `.mmdb` at config-parse time, it is **only emitted when the DB is present** — the container-start entrypoint `25-vbwd-geoip2.sh` writes `/etc/nginx/conf.d/00-vbwd-geoip2.conf`:

- **DB present** → real `geoip2 { $geoip2_country_code source=$vbwd_geo_client_ip country iso_code; }` + a trusted-client-hop map (`$vbwd_geo_client_ip` = first `X-Forwarded-For` entry, else `$remote_addr`).
- **DB absent** → a map defining `$geoip2_country_code` as empty ⇒ nginx still starts, every visitor reads as "unknown country", and (unless `block_unknown_country`) the site serves normally.

Either branch is `nginx -t`-validated, so a missing DB never turns into a start-up outage.

### The `geo-block.json` contract

`GeoBlockNginxWriter` writes the descriptor on every admin PUT and on `flask cms geo-block sync`, **atomically** (temp file + `os.replace`, so a concurrent njs read never sees a truncated file). The njs handler reads it with a **5 s in-process TTL cache** — no nginx reload is ever needed.

- **Host path:** `${VAR_DIR}/cms/nginx/geo-block.json` (via `filesystem_manager.for_plugin('cms')`)
- **In-container path (njs reads):** `/etc/nginx/geo/geo-block.json` (bind-mounted read-only)

```json
{
  "enabled": true,
  "allowed_codes": ["AT", "CH", "DE"],
  "bypass_query": "allowme=yes",
  "bypass_cookie_ttl_days": 30,
  "blocked_target_slug": "/locked",
  "block_unknown_country": false,
  "bypass_secret": "<64-char hex>"
}
```

### Bypass cookie

Token = `base64url(exp_seconds).hmacHex(bypass_secret, exp_seconds)` (HMAC-SHA256; the HMAC signs the decimal exp string). Cookie `vbwd_geo_bypass`, flags `Secure; HttpOnly; SameSite=Lax; Path=/; Max-Age = bypass_cookie_ttl_days`. Verification recomputes the HMAC (constant-time compare) and checks the expiry is in the future; a tampered or expired token is ignored.

`bypass_secret` is a **dedicated var-file secret** (`${VAR_DIR}/cms/nginx/bypass-secret`, 32 random bytes → 64 hex chars, generated once and reused so cookies survive restarts) — **NOT `JWT_SECRET_KEY`**. Spreading the app secret into an nginx-readable file would widen its blast radius.

### Fail-open

The handler no-ops (serves as today) when: `enabled` is false, the config JSON is missing/unparseable, or the mmdb is absent (unknown country + `block_unknown_country=false`). A bad config or missing DB **never** locks the site.

The `geoip2` block is only emitted at container-start when the mmdb is present (above).

---

## Enforcement layer 2 — Flask middleware (S120)

`GeoIpResolver.before_request()` sets `g.geoip_country` (ISO alpha-2, upper) once per request; `CmsGeoBlockMiddleware.before_request()` (registered after the resolver) enforces. Decision order (`src/middleware/geo_block_middleware.py`):

1. `is_enabled` false ⇒ pass. (Config unavailable — e.g. table not yet migrated — also fails open, with a warning + a rollback to clear any poisoned transaction.)
2. **Passthrough** (never blocked): the routing middleware's set (`/api/`, `/admin/`, `/uploads/`, `/_vbwd/`, robots/sitemap), static assets (by extension), and the `blocked_target_slug` page + its sub-paths (loop-guard). Keeping `/admin` + `/api` open means the operator can always log in and the locked page's SPA/API still work.
3. **Bypass GET**: if the query carries the configured `key=value`, mint `vbwd_geo_bypass` and `302` to the same path with that param stripped.
4. **Bypass cookie**: a valid `vbwd_geo_bypass` ⇒ pass.
5. **Country gate**: `g.geoip_country` in the derived allowed set ⇒ pass; unknown/`None` ⇒ pass unless `block_unknown_country`; otherwise `302 → blocked_target_slug` (or `451` when empty).

Block responses carry `Cache-Control: private, no-store` so a CDN/prerender never caches a block for an allowed visitor (or vice-versa).

`GeoIpResolver` resolution order: (a) an optional trusted country header (e.g. `CF-IPCountry`) **when configured** — off by default; (b) a MaxMind mmdb lookup on the trusted client IP (last-N hop of `X-Forwarded-For` per `trusted_proxy_count`, default 1). A missing/unreadable DB ⇒ `None` + a single logged warning. The `geoip2` package is imported lazily (installed from the plugin's `requirements.txt` at runtime).

> **Bonus:** with `g.geoip_country` now populated, the routing subsystem's pre-existing `country` match_type / `CountryMatcher` becomes usable for ordinary redirect rules too — no change to that code. (See `cms-routing.md`.)

---

## Provisioning the GeoLite2 database

The country mmdb is **not** baked into the image — it is bind-mounted so it can be refreshed without a rebuild:

- **Host:** `${VAR_DIR}/cms/geoip/GeoLite2-Country.mmdb`
- **In fe-user container:** `/etc/nginx/geoip/GeoLite2-Country.mmdb` (read-only)

Two free sources, both in MaxMind MMDB format:

1. **MaxMind GeoLite2-Country** — free account + a license key. Download the `GeoLite2-Country` MMDB, or run `geoipupdate` (with the key) for automatic refresh. The MaxMind EULA requires **attribution** in your product/privacy documentation.
2. **DB-IP IP-to-Country Lite** — no account, CC-BY licensed, same MMDB filename/format. Drop it in as `GeoLite2-Country.mmdb`.

Note: IP→country lookups cannot geolocate `localhost` / private IPs — those resolve as "unknown country" (fail-open unless `block_unknown_country`).

---

## Local testing

The njs layer honours a dev **test-override header** so you can exercise the block from localhost without a foreign IP or even the mmdb:

```
X-VBWD-Geo-Test: DE
```

It is gated by `GEO_TEST_ALLOW=1` (an env var exposed to njs via `env GEO_TEST_ALLOW;` in the image `nginx.conf`; the fe-user image defaults it to empty). Set `GEO_TEST_ALLOW=1` **only** on a local/dev instance — in prod the header is inert (a pure no-op).

Example: with the block on, `DE` **not** in the allowed list, and `GEO_TEST_ALLOW=1`:

```bash
curl -s -o /dev/null -w '%{http_code} %{redirect_url}\n' \
  -H 'X-VBWD-Geo-Test: DE' http://localhost:8080/
# → 302 /locked

curl -s -o /dev/null -D - \
  -H 'X-VBWD-Geo-Test: DE' 'http://localhost:8080/?allowme=yes' | grep -i set-cookie
# → Set-Cookie: vbwd_geo_bypass=...; ... Secure; HttpOnly; SameSite=Lax
```

---

## Enable checklist (ops)

1. **Enable/disable countries** at `/admin/settings/tax-and-countries` — this *is* the allowed list.
2. **Provision the mmdb** at `${VAR_DIR}/cms/geoip/GeoLite2-Country.mmdb` (MaxMind license key = a secret; or DB-IP Lite).
3. **Build a `/locked` CMS page** (a normal CMS page at the `blocked_target_slug`).
4. **Enable + set the bypass** in the "Blocked countries" tab; self-test with the bypass param before flipping it on.
5. **fe-user image** must carry the geoip2 + njs modules — rebuild/pull. After a mmdb or allowed-country change, run `flask cms geo-block sync` (or save the tab) to republish `geo-block.json`.

`flask cms geo-block sync` regenerates `${VAR_DIR}/cms/nginx/geo-block.json` from the current config **without** a config PUT — useful when the allowed set changed at tax-and-countries independently of the geo-block config.

---

## GDPR note

Resolving an IP to a country is **processing** — mention it in your privacy policy (and add MaxMind attribution if you use GeoLite2). The bypass token and the resolved country are **transient**: no IP is stored beyond the request, and the cookie carries only an opaque expiry + HMAC.

---

## Related

- `cms-routing.md` — the routing-rule engine that shares the "Blocked countries" tab and whose dormant `country` matcher this feature activates.
- `import-export.md` — moving CMS content (including the `/locked` page) between instances.

For the full design + task breakdown see the sprint docs `S120_cms_geo_blocking_with_bypass.md` (backend + Flask middleware) and `S120_1_nginx_layer_geo_enforcement.md` (the nginx/njs layer) under `docs/dev_log/20260706/sprints/`.
