"""cms SEO seam — ``<lastmod>`` must be valid W3C Datetime in the rendered
sitemap, whatever a provider hands in.

Google's Sitemaps report rejects the WHOLE sitemap ("could not be read") when a
``lastmod`` specifies a time WITHOUT a timezone, carries sub-second precision,
or is otherwise malformed. Prod ``cms_post.updated_at`` is a naive datetime, so
``.isoformat()`` yields e.g. ``2026-07-01T19:30:18.032923`` — time, no zone,
microseconds — exactly the forbidden shape. The render layer is the single
choke point every provider's entry passes through, so it normalises there:

  * naive datetime string  -> assume UTC, drop microseconds, append ``Z``;
  * timezone-aware string  -> keep the offset, drop microseconds;
  * date-only string       -> pass through (already valid);
  * unparseable garbage    -> omit ``<lastmod>`` rather than emit an invalid one.

Engineering requirements (binding, restated): TDD-first (RED before the
normaliser existed); SOLID/DI/DRY; Liskov; clean code; no overengineering.
Guard: ``bin/pre-commit-check.sh --plugin cms --full``.
"""
import re

from plugins.cms.src import seo_routes
from plugins.cms.src.services.seo_registry import SitemapEntry


def _render(lastmod):
    entry = SitemapEntry(loc="https://vbwd.cc/x", lastmod=lastmod)
    return seo_routes._render_url_element(entry)


def _lastmod_value(xml: str):
    match = re.search(r"<lastmod>(.*?)</lastmod>", xml)
    return match.group(1) if match else None


def test_naive_microsecond_datetime_becomes_utc_zulu_no_micros():
    value = _lastmod_value(_render("2026-07-01T19:30:18.032923"))
    assert value == "2026-07-01T19:30:18Z"


def test_naive_datetime_without_micros_gets_zulu():
    value = _lastmod_value(_render("2026-07-01T19:30:18"))
    assert value == "2026-07-01T19:30:18Z"


def test_timezone_aware_datetime_preserved_minus_micros():
    value = _lastmod_value(_render("2026-01-02T00:00:00.500000+00:00"))
    assert value == "2026-01-02T00:00:00+00:00"


def test_zulu_input_normalised_to_explicit_offset():
    # ``Z`` and ``+00:00`` are both valid W3C Datetime; we emit the offset form.
    value = _lastmod_value(_render("2026-01-02T05:06:07Z"))
    assert value == "2026-01-02T05:06:07+00:00"


def test_date_only_passes_through():
    value = _lastmod_value(_render("2026-07-01"))
    assert value == "2026-07-01"


def test_unparseable_lastmod_is_omitted():
    xml = _render("not-a-date")
    assert "<lastmod>" not in xml


def test_no_lastmod_stays_absent():
    xml = _render(None)
    assert "<lastmod>" not in xml
