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
