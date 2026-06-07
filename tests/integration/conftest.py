"""Shared fixtures for the cms SEO integration suites (test-isolation hygiene).

Two pieces of process-global / persisted state strand the SEO sitemap tests
when several suites run together (the whole-backend ``pre-commit-check.sh
--full`` run):

  1. **The sitemap provider registry.** The cms provider is registered into the
     module-level ``seo_registry`` at plugin enable (boot). Sibling SEO suites'
     autouse fixtures call ``seo_registry.clear_sitemap_providers()`` /
     ``unregister_seo_pipeline()`` on teardown, so a later test that relies on
     the boot registration finds an empty registry and ``/sitemap.xml`` yields
     nothing.
  2. **The persisted cms config blob.** ``_sitemap_config()`` reads the
     ``sitemap_*`` filter keys from the live ``config_store`` (the ``_test`` DB).
     If a prior run / demo seed left ``sitemap_include_terms`` populated, every
     post lacking one of those terms is filtered out of the sitemap — again an
     empty urlset. The shipped ``DEFAULT_CONFIG`` filter lists are empty, so the
     no-filter baseline is the correct one for any test that does not itself set
     a filter.

These autouse fixtures make every cms SEO integration test self-sufficient:
they register the cms sitemap provider through the real wiring
(``register_seo_pipeline``) and reset the sitemap-filter config keys to their
no-filter defaults, then restore the prior state on teardown — so no suite can
strand the registry or the config for another, in any collection order.

Engineering requirements (binding, restated): TDD-first (fixture hygiene proven
by the combined run); DevOps-first (clean local + CI from cold start); SOLID/
DI/DRY (one home for the SEO provider/config setup, via the real wiring — no
hand-rolled fake provider); Liskov (the no-filter default is the contract a
missing config implies); clean code; no overengineering. Quality guard:
``bin/pre-commit-check.sh --plugin cms --full``.
"""
import pytest
from flask import current_app

from plugins.cms.src.services import seo_registry
from plugins.cms.src.services.seo_wiring import (
    register_seo_pipeline,
    unregister_seo_pipeline,
)


# The sitemap-filter keys an admin can set via PUT /admin/cms/seo/settings.
# A test that does not set them must see the shipped no-filter defaults (empty
# lists / include-all), independent of whatever a prior run persisted.
_SITEMAP_FILTER_DEFAULTS = {
    "sitemap_include_pages": True,
    "sitemap_excluded_slugs": [],
    "sitemap_include_terms": [],
    "sitemap_exclude_terms": [],
}


@pytest.fixture(autouse=True)
def _seo_sitemap_filter_baseline(db):
    """Reset the cms sitemap-filter config keys to their no-filter defaults.

    Snapshots the cms config blob, forces the four ``sitemap_*`` filter keys to
    the shipped (no-filter) values for the test, then restores the original blob
    on teardown. A test that PUTs its own filters (the S56 settings suite) still
    overrides these for the duration of its body.
    """
    store = current_app.config_store
    saved = dict(store.get_config("cms") or {})
    store.save_config("cms", {**saved, **_SITEMAP_FILTER_DEFAULTS})
    yield
    store.save_config("cms", saved)


@pytest.fixture(autouse=True)
def _seo_sitemap_provider_registered(db, _seo_sitemap_filter_baseline):
    """Guarantee the cms sitemap provider is registered for each SEO test.

    Uses the SAME production wiring ``on_enable`` uses (``register_seo_pipeline``)
    so the provider reads the live ``db.session`` and config. Snapshots the
    registry, registers the cms pipeline, then restores the prior providers on
    teardown so no suite strands the registry for another (any collection order).
    """
    saved_providers = seo_registry.list_sitemap_providers()
    seo_registry.clear_sitemap_providers()
    register_seo_pipeline()
    yield
    unregister_seo_pipeline()
    seo_registry.clear_sitemap_providers()
    for provider in saved_providers:
        seo_registry.register_sitemap_provider(provider)
