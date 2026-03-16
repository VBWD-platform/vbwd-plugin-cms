# CMS Routing Rules — Developer Guide

The routing rules engine lets an admin configure URL redirect and rewrite behaviour through the backoffice with zero SSH access and zero downtime. Rules are stored in PostgreSQL and evaluated at two independent layers: **nginx** (network level, no Python overhead) and **Flask middleware** (per-request, no nginx reload).

---

## Quick Start — Setting a Homepage

The most common first use case: a user hits `example.com/` and you want them to land on a specific CMS page.

### Option A — Redirect (URL changes in the browser)

A user visits `example.com/` → browser is redirected to `example.com/home`.

1. Go to **Admin → CMS → Routing Rules → Add Rule**
2. Fill in:

   | Field | Value |
   |-------|-------|
   | Name | `Homepage redirect` |
   | Priority | `100` (high number = evaluated last, good for a catch-all default) |
   | Match type | `default` |
   | Match value | *(leave empty)* |
   | Target slug | `home` |
   | Redirect code | `302` (use `301` only once the URL is permanent) |
   | Transparent rewrite | off |
   | Layer | `middleware` |
   | Active | on |

3. Click **Save**. No nginx reload needed — middleware rules take effect immediately.

Visiting `example.com/` now returns a `302 → /home`.

### Option B — Silent rewrite (URL stays as `/`)

A user visits `example.com/` and sees the `home` page content without the URL changing.

Same steps as Option A, but set:
- **Transparent rewrite** → on
- **Layer** → `middleware`

The middleware returns an `X-Accel-Redirect` header pointing nginx to the `home` page internally. The browser always shows `example.com/`.

> **Note:** Silent rewrite requires nginx as the upstream proxy. In local dev without nginx the middleware falls back transparently — you will see the redirect in the response headers but the URL will still change. This is expected in dev.

### Option C — Language-based homepage

Route users to a language-specific homepage based on their browser language:

| Priority | Match type | Match value | Target slug |
|----------|-----------|-------------|-------------|
| `10` | `language` | `de` | `de/home` |
| `10` | `language` | `fr` | `fr/home` |
| `100` | `default` | *(empty)* | `home` |

Rules are evaluated in priority order (lowest number first). A German-language browser hits the `language=de` rule and is sent to `/de/home`. All others fall through to the `default` rule and land on `/home`.

### Verifying a rule is working

```bash
# Check the rule was saved
curl -s -H "Authorization: Bearer <admin-token>" \
  http://localhost:5000/api/v1/admin/cms/routing-rules | python3 -m json.tool

# Simulate a request hitting the middleware (replace with your slug)
curl -v -L http://localhost:8080/
# Expect: HTTP/1.1 302 Found  →  Location: /home
```

---

## Architecture

```
Admin UI (fe-admin /admin/cms/routing-rules)
  └─► POST /api/v1/admin/cms/routing-rules
        └─► CmsRoutingService.create_rule()
              └─► CmsRoutingRuleRepository.save()
              └─► CmsRoutingService.sync_nginx()  ← only when layer = "nginx"
                    └─► NginxConfGenerator.generate()
                    └─► NginxConfGenerator.write_and_validate()  → cms_routing.conf
                    └─► SubprocessNginxReloadGateway.reload()    → nginx -s reload

Incoming HTTP request
  └─► nginx (reads cms_routing.conf geo/map blocks)
        └─► 301/302 if nginx-layer rule matches
        └─► OR proxy_pass → Flask app
                  └─► CmsRoutingMiddleware.before_request()
                        └─► CmsRoutingService.evaluate(ctx)
                              └─► matcher_for(match_type).matches(rule, ctx)
                                    └─► redirect() or X-Accel-Redirect or None
```

---

## File Structure

```
plugins/cms/src/
├── models/
│   └── cms_routing_rule.py          # SQLAlchemy model
├── repositories/
│   └── routing_rule_repository.py   # DB access layer
├── services/routing/
│   ├── __init__.py
│   ├── matchers.py                  # RequestContext, RedirectInstruction, 6 matchers
│   ├── nginx_conf_generator.py      # Generates cms_routing.conf
│   ├── nginx_reload_gateway.py      # Subprocess + stub gateway
│   └── routing_service.py           # Orchestration service
└── middleware/
    └── routing_middleware.py        # Flask before_request hook

plugins/cms/tests/unit/
├── services/
│   ├── test_routing_matchers.py
│   └── test_routing_service.py
└── middleware/
    └── test_routing_middleware.py
```

---

## Data Model — `CmsRoutingRule`

**Table:** `cms_routing_rules`
**File:** `src/models/cms_routing_rule.py`

Extends `BaseModel` (UUID primary key, `created_at`, `updated_at`, `version`).

| Column | Type | Default | Description |
|--------|------|---------|-------------|
| `name` | String(120) | required | Human-readable label |
| `is_active` | Boolean | `true` | Disabled rules are skipped by both layers |
| `priority` | Integer | `0` | Lower number = evaluated first |
| `match_type` | String(32) | required | One of: `default`, `language`, `ip_range`, `country`, `path_prefix`, `cookie` |
| `match_value` | String(255) | `null` | Condition value; `null` for `default` |
| `target_slug` | String(255) | required | CMS slug or absolute path to redirect/rewrite to |
| `redirect_code` | Integer | `302` | Must be `301` or `302` |
| `is_rewrite` | Boolean | `false` | `true` = transparent rewrite (URL unchanged); `false` = HTTP redirect |
| `layer` | String(16) | `"middleware"` | `"nginx"` or `"middleware"` |

### `match_value` format per `match_type`

| `match_type` | `match_value` example | Notes |
|---|---|---|
| `default` | `null` | Always matches; use as fallback with highest priority number |
| `language` | `"de"` | ISO 639-1 two-letter code |
| `ip_range` | `"203.0.113.0/24"` | CIDR notation; single IPs also valid (`"1.2.3.4/32"`) |
| `country` | `"DE"` or `"DE,AT,CH"` | ISO 3166-1 alpha-2; comma-separated for multiple countries |
| `path_prefix` | `"/old-pricing"` | Matches any path starting with this string |
| `cookie` | `"vbwd_lang=de"` | Only the `vbwd_lang` cookie is currently supported |

---

## Evaluation Layers

### `middleware` layer

Evaluated by `CmsRoutingMiddleware.before_request()` on every Flask request that does not match a passthrough prefix.

**Passthrough prefixes** (always skipped, never evaluated):
```
/api/
/admin/
/uploads/
/_vbwd/
```

Rules ordered by `priority ASC`, then `created_at ASC`. First match wins.

### `nginx` layer

Nginx-layer rules are written to `cms_routing.conf` as `geo` and `map` blocks. They are evaluated at the network level before the request reaches Python.

Supported `match_type` values for nginx layer: `ip_range`, `language`, `cookie`.
(`country`, `path_prefix`, `default` are supported by the middleware layer only.)

`sync_nginx()` is called automatically on every create/update/delete of an nginx-layer rule.

---

## Request Context

**File:** `src/services/routing/matchers.py`

```python
@dataclass(frozen=True)
class RequestContext:
    path: str             # request.path
    accept_language: str  # Accept-Language header value
    remote_addr: str      # request.remote_addr
    geoip_country: Optional[str]  # g.geoip_country (set by GeoIP extension if enabled)
    cookie_lang: Optional[str]    # request.cookies.get("vbwd_lang")
```

Built in `CmsRoutingMiddleware.before_request()` and passed to `CmsRoutingService.evaluate()`.

---

## Matchers

**File:** `src/services/routing/matchers.py`

All matchers implement the same interface:

```python
def matches(self, rule: CmsRoutingRule, ctx: RequestContext) -> bool
```

| Class | `match_type` | Logic |
|-------|-------------|-------|
| `DefaultMatcher` | `"default"` | Always returns `True` |
| `LanguageMatcher` | `"language"` | Cookie lang checked first; falls back to first 2 chars of `Accept-Language` header |
| `IpRangeMatcher` | `"ip_range"` | CIDR check via `ipaddress.ip_network`; returns `False` on invalid IP or CIDR |
| `CountryMatcher` | `"country"` | Compares `ctx.geoip_country` against comma-separated list; returns `False` when `geoip_country` is `None` |
| `PathPrefixMatcher` | `"path_prefix"` | `ctx.path.startswith(rule.match_value)` |
| `CookieMatcher` | `"cookie"` | Parses `vbwd_lang=<value>`; only `vbwd_lang` key is supported |

Use `matcher_for(match_type)` to retrieve the singleton instance:

```python
from plugins.cms.src.services.routing.matchers import matcher_for

m = matcher_for("language")   # returns LanguageMatcher()
m.matches(rule, ctx)
```

---

## Redirect Instruction

```python
@dataclass(frozen=True)
class RedirectInstruction:
    location: str   # absolute path, e.g. "/de/home"
    code: int       # 301 or 302
    is_rewrite: bool
```

- `is_rewrite=False` → `Flask.redirect(location, code=code)` — browser URL changes
- `is_rewrite=True` → `Response` with `X-Accel-Redirect: location` header — URL stays (requires nginx as upstream)

---

## Service API

**File:** `src/services/routing/routing_service.py`

```python
class CmsRoutingService:
    def list_rules(self) -> List[dict]
    def create_rule(self, data: dict) -> dict
    def update_rule(self, rule_id: str, data: dict) -> dict
    def delete_rule(self, rule_id: str) -> None         # raises CmsRoutingRuleNotFoundError
    def sync_nginx(self) -> None
    def evaluate(self, ctx: RequestContext) -> Optional[RedirectInstruction]
```

### Validation rules (enforced in `_validate`)

| Field | Constraint |
|-------|-----------|
| `match_type` | Must be one of the 6 allowed values |
| `redirect_code` | Must be `301` or `302` |
| `target_slug` | Must not be empty or whitespace-only |
| `priority` | Must be a non-negative integer |
| `layer` | Must be `"nginx"` or `"middleware"` |

Validation errors raise `ValueError` with a semicolon-separated message.

### `sync_nginx()` safety gate

```
sync_nginx()
  ├── generate conf string from active nginx-layer rules
  ├── write_and_validate(conf_str, path)
  │     ├── write to temp file
  │     ├── run nginx -t (skipped gracefully if nginx not found)
  │     └── on non-zero exit: raise NginxConfInvalidError  ← reload() is NOT called
  └── nginx_gateway.reload()
```

If `write_and_validate` raises `NginxConfInvalidError`, the gateway reload is skipped and the error propagates to the caller (the API route returns a 500).

---

## Repository

**File:** `src/repositories/routing_rule_repository.py`

```python
class CmsRoutingRuleRepository:
    def find_all(self) -> List[CmsRoutingRule]                      # all rules, ordered by priority
    def find_all_active(self) -> List[CmsRoutingRule]               # is_active=True, ordered
    def find_all_active_for_layer(self, layer: str) -> List[CmsRoutingRule]
    def find_by_id(self, rule_id: str) -> Optional[CmsRoutingRule]
    def save(self, rule: CmsRoutingRule) -> CmsRoutingRule
    def delete(self, rule_id: str) -> bool
```

Constructor-injected `session`. Never imported directly from routes — instantiated in the `_routing_svc()` factory function in `src/routes.py`.

---

## Nginx Conf Generator

**File:** `src/services/routing/nginx_conf_generator.py`

`generate(rules, default_slug)` produces:
- `geo $remote_addr $cms_ip_route { ... }` — for `ip_range` rules
- `map $http_accept_language $cms_lang_route { ... }` — for `language` rules
- `map $cookie_vbwd_lang $cms_cookie_route { ... }` — for `cookie` rules

`write_and_validate(conf_str, path)`:
1. Writes to a temp `.conf` file
2. Runs `nginx -t -c <tempfile>` (timeout 5 s)
3. If nginx is not installed, skips validation silently (dev environment)
4. On `returncode != 0`, raises `NginxConfInvalidError` with nginx stderr
5. Writes conf to the target path

---

## Nginx Reload Gateway

**File:** `src/services/routing/nginx_reload_gateway.py`

| Class | Use | Behaviour |
|-------|-----|-----------|
| `SubprocessNginxReloadGateway` | Production | Runs `nginx -s reload`; raises `NginxReloadError` on failure; silently skips if nginx not found |
| `StubNginxReloadGateway` | Tests | Increments `reload_count` on each call; never touches the filesystem |

The factory in `src/routes.py` uses `StubNginxReloadGateway` when `app.config["TESTING"]` is `True`.

---

## API Endpoints

All admin endpoints require `@require_admin`.

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/api/v1/admin/cms/routing-rules` | admin | List all rules, ordered by priority |
| `POST` | `/api/v1/admin/cms/routing-rules` | admin | Create rule |
| `GET` | `/api/v1/admin/cms/routing-rules/<id>` | admin | Get single rule |
| `PUT` | `/api/v1/admin/cms/routing-rules/<id>` | admin | Update rule (partial update supported) |
| `DELETE` | `/api/v1/admin/cms/routing-rules/<id>` | admin | Delete rule |
| `POST` | `/api/v1/admin/cms/routing-rules/reload` | admin | Force nginx conf regeneration and reload |
| `GET` | `/api/v1/cms/routing-rules` | public | Returns all active rules with `layer="nginx"` (used by nginx on boot) |

### Request payload (POST / PUT)

```json
{
  "name": "German users",
  "is_active": true,
  "priority": 10,
  "match_type": "language",
  "match_value": "de",
  "target_slug": "de/home",
  "redirect_code": 302,
  "is_rewrite": false,
  "layer": "middleware"
}
```

For `PUT`, only include fields you want to change. Omitted fields are left unchanged.

### Response shape (single rule)

```json
{
  "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "name": "German users",
  "is_active": true,
  "priority": 10,
  "match_type": "language",
  "match_value": "de",
  "target_slug": "de/home",
  "redirect_code": 302,
  "is_rewrite": false,
  "layer": "middleware",
  "created_at": "2026-03-15T10:00:00",
  "updated_at": "2026-03-15T10:00:00"
}
```

### Error responses

| HTTP | When |
|------|------|
| 400 | Validation failure (invalid `match_type`, bad `redirect_code`, empty `target_slug`, etc.) |
| 401 | Missing or invalid auth token |
| 403 | Authenticated but not admin |
| 404 | Rule ID not found |
| 500 | `NginxConfInvalidError` — conf generated but nginx validation failed |

---

## Database Migration

**File:** `alembic/versions/20260315_create_cms_routing_rules.py`

```bash
# Apply migration
docker-compose exec api flask db upgrade

# Rollback
docker-compose exec api flask db downgrade -1
```

Indexes created:
- `ix_cms_routing_rules_priority` on `priority`
- `ix_cms_routing_rules_layer` on `layer`

---

## Configuration

Routing config lives under the `"routing"` key in `plugins/config.json` (not `plugins/cms/config.json`):

```json
{
  "routing": {
    "enabled": true,
    "default_slug": "home1",
    "default_redirect_code": 302,
    "nginx_conf_path": "/etc/nginx/conf.d/cms_routing.conf",
    "nginx_reload_command": "nginx -s reload",
    "nginx_enabled": true,
    "geoip": {
      "enabled": false,
      "mmdb_path": "/etc/nginx/GeoLite2-Country.mmdb"
    }
  }
}
```

| Key | Description |
|-----|-------------|
| `default_slug` | Slug used as the `default` value in generated nginx `geo`/`map` blocks |
| `nginx_conf_path` | Absolute path where `cms_routing.conf` is written |
| `nginx_reload_command` | Command passed to `SubprocessNginxReloadGateway` (split on spaces) |
| `geoip.enabled` | When `true`, the GeoIP extension sets `g.geoip_country` per request |
| `geoip.mmdb_path` | Path to a MaxMind GeoLite2-Country `.mmdb` database file |

---

## Testing

### Unit tests

```bash
# Matchers only
docker compose run --rm test python -m pytest plugins/cms/tests/unit/services/test_routing_matchers.py -v

# Service only
docker compose run --rm test python -m pytest plugins/cms/tests/unit/services/test_routing_service.py -v

# Middleware only
docker compose run --rm test python -m pytest plugins/cms/tests/unit/middleware/test_routing_middleware.py -v

# All routing tests
docker compose run --rm test python -m pytest plugins/cms/tests/unit/services/test_routing_matchers.py \
  plugins/cms/tests/unit/services/test_routing_service.py \
  plugins/cms/tests/unit/middleware/test_routing_middleware.py -v
```

### Integration tests (requires running PostgreSQL)

```bash
make test-integration
```

### Testing with `StubNginxReloadGateway`

The `StubNginxReloadGateway` is injected automatically when `app.config["TESTING"] = True`. In unit tests you can also inject it directly:

```python
from plugins.cms.src.services.routing.nginx_reload_gateway import StubNginxReloadGateway
from plugins.cms.src.services.routing.nginx_conf_generator import NginxConfGenerator
from plugins.cms.src.services.routing.routing_service import CmsRoutingService

stub_gateway = StubNginxReloadGateway()
svc = CmsRoutingService(
    rule_repo=mock_repo,
    conf_generator=NginxConfGenerator(),
    nginx_gateway=stub_gateway,
    config={"routing": {"default_slug": "home", "nginx_conf_path": "/tmp/test.conf"}},
)

svc.sync_nginx()
assert stub_gateway.reload_count == 1
```

---

## Extending

### Adding a new `match_type`

1. Add a new matcher class to `src/services/routing/matchers.py`:

   ```python
   class MyMatcher:
       def matches(self, rule, ctx: RequestContext) -> bool:
           if rule.match_type != "my_type":
               return False
           # your logic
           return True
   ```

2. Register it in the `_MATCHERS` dict at the bottom of the same file:

   ```python
   _MATCHERS = {
       ...
       "my_type": MyMatcher(),
   }
   ```

3. Add `"my_type"` to `CmsRoutingService.VALID_MATCH_TYPES`.

4. Add unit tests in `tests/unit/services/test_routing_matchers.py`.

5. Update the fe-admin `RoutingRuleForm.vue` select options and placeholder map.

No other files need to change.

### Adding nginx-level support for a new match type

Add the corresponding `geo` or `map` block generation in `NginxConfGenerator.generate()` and update `NginxConfGenerator.write_and_validate()` tests.
