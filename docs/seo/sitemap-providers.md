# Sitemap providers (registry v2, S154)

cms owns the sitemap. Any plugin with public pages (shop, booking, dataset,
ghrm, ...) contributes URLs by registering a **sitemap provider**. cms never
imports a domain plugin. The contract is duck-typed and lives in
`plugins/cms/src/services/seo_registry.py`.

## URL scheme

| URL | Body |
|---|---|
| `/sitemap.xml` | Always a `<sitemapindex>`. It lists one `<sitemap>` per provider chunk and is built from `count()` alone, so no rows are read. |
| `/sitemap-<name>-<n>.xml` | One `<urlset>` with at most 50,000 URLs, from `provider.page((n-1)*50000, 50000)`. An unknown `<name>` or an `n` outside `1..ceil(count/50000)` returns 404. |
| `/sitemap-<n>.xml` | The pre-S154 numbering, kept because it is already submitted to Search Console. It serves the n-th chunk of the index in place: 200, with the same body as the canonical chunk URL. |

Every sitemap response is `application/xml; charset=utf-8` with
`Cache-Control: public, max-age=3600` and an `ETag`, so `If-None-Match`
returns 304. `robots.txt` keeps advertising `Sitemap: <site>/sitemap.xml`.

## Contract

```python
class ISitemapProvider(Protocol):
    name: str                                  # stable, url-safe: "shop-products"
    def count(self) -> int: ...                # length of the sequence page() walks
    def page(self, offset: int, limit: int) -> Iterable[SitemapEntry]: ...
```

- **`name`** is a set of `[a-z0-9]` words joined by single `-`. It appears in
  public URLs, so never rename it. Registration is idempotent by name: a second
  registration replaces the first and keeps its position.
- **`page()`** must use a stable order. Use `ORDER BY <indexed column>` with
  `LIMIT/OFFSET`, or a keyset. Never load every row.
- **Public, indexable URLs only (D1).** cms also drops private paths centrally
  (`seo_private_path_prefixes`, default `/dashboard,/tuktuk,/pay`). Providers
  don't repeat that rule. Because `page()` may filter rows too, a chunk can
  hold fewer than 50,000 URLs, and `count()` is an upper bound.
- **`SitemapEntry`** has `loc` (absolute, or root-relative such as
  `/shop/product/x`), plus optional `lastmod` (ISO datetime or date),
  `changefreq`, `priority`, and `alternates` (`[{"hreflang", "href"}]`).
- **Legacy providers** that only expose `sitemap_entries() -> list` still
  work. They are wrapped by `LegacySitemapProviderAdapter`, which uses
  count = len and page = slice, and their name is derived from the class name.
  Use v2 for anything large.

## Example: a domain plugin (register only when cms is enabled, D3)

```python
class ShopProductSitemapProvider:
    name = "shop-products"

    def __init__(self, session_factory):
        self._session_factory = session_factory

    def _query(self):
        return self._session_factory().query(Product).filter(Product.is_active.is_(True))

    def count(self) -> int:
        return self._query().count()

    def page(self, offset, limit):
        for product in self._query().order_by(Product.id).offset(offset).limit(limit):
            yield SitemapEntry(loc=f"/shop/product/{product.slug}",
                               lastmod=product.updated_at.isoformat() if product.updated_at else None)

# ShopPlugin.on_enable / on_disable
def _sitemap_registry():
    try:
        from plugins.cms.src.services import seo_registry   # cms is optional
    except ImportError:
        return None
    return seo_registry

registry = _sitemap_registry()
if registry is not None:
    registry.register_sitemap_provider(ShopProductSitemapProvider(lambda: db.session))
# on_disable: registry.unregister_sitemap_provider(provider)
```

Also gate the registration on cms actually being *enabled*, not only
importable. Use the same check the plugin already uses for its other optional
cms integrations.

## cms providers and the indexable-type switches (S154 P2)

cms registers three providers. Each switch lives in the cms plugin config
(`config.json` default, `admin-config.json` "Indexing" tab in fe-admin) and is
read live on every sitemap request.

| Provider | URLs | Switch (default) |
|---|---|---|
| `cms` | published pages (`type=page`) and posts (`type=post`) at their canonical URL | `seo_index_pages` (on), `seo_index_posts` (on) |
| `cms-categories` | `/category/<slug>` for each category with at least one published post | `seo_index_categories` (off) |
| `cms-tags` | `/tag/<slug>` for each core tag carried by at least one published cms post | `seo_index_tags` (off) |

- Switched-off types are filtered in SQL, so `count()` and `page()` agree. A
  switched-off archive provider has `count() == 0`, and `/sitemap.xml` lists no
  `sitemap-cms-categories-*` / `sitemap-cms-tags-*` chunk for it.
- Archive URLs come from `term_archive_path` (the same map the terms API uses
  for `archive_url`). `lastmod` is the newest published post's `updated_at`
  (for categories, or the term's own `updated_at` if newer), computed in the
  same grouped query.
- Categories with `seo_excluded` are skipped. Term slugs in
  `sitemap_exclude_terms` are skipped for both archive families. Tags have no
  `seo_excluded` flag (they live in the core tag index).

### Precedence and the pre-S154 keys

`get_config("cms")` returns the saved blob only, so "saved" means the key is
present and not null.

1. `seo_index_pages`, when saved, wins.
2. Else the legacy `sitemap_include_pages`, when saved.
3. Else the default (on).

`seo_index_posts`, `seo_index_categories` and `seo_index_tags` have no legacy
key. The S56 SEO settings endpoint (`/api/v1/admin/cms/seo/settings`) keeps
working: a PUT of `sitemap_include_pages` also writes `seo_index_pages`, and a
GET reports the effective pages value under `sitemap_include_pages`.

`sitemap_include_terms` and `sitemap_exclude_terms` keep their S56 meaning as
post filters (restrict to / drop posts carrying those term slugs);
`sitemap_exclude_terms` also drops the matching term archives.

Note: the generic fe-admin plugin form saves every `config.json` key with its
default. An install that had `sitemap_include_pages: false` and then saves the
cms plugin form without unticking "Index pages" will index pages again.
