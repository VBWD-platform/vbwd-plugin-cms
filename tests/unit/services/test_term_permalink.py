"""Unit: term_archive_path — the fixed (term_type, slug) → archive path map.

Inc 1 of the CMS term-archives feature serves category archives at
``category/<slug>`` and tag archives at ``tag/<slug>`` via fixed, permalink-
independent prefixes. This oracle pins that single source of truth so every read
surface (serialization, the term-resolution endpoint, the fe links) agrees.

Engineering requirements (binding, restated): TDD-first (this RED set);
DevOps-first (pure function, cold local + CI); SOLID/DI/DRY (one home for the
prefix convention); Liskov; clean code; no overengineering. Quality guard:
``bin/pre-commit-check.sh --plugin cms --full``.
"""
from plugins.cms.src.services.term_permalink import term_archive_path


def test_category_term_maps_to_category_prefix():
    assert term_archive_path("category", "gadgets") == "category/gadgets"


def test_tag_term_maps_to_tag_prefix():
    assert term_archive_path("tag", "vue") == "tag/vue"


def test_nested_category_slug_is_preserved():
    assert term_archive_path("category", "electronics/phones") == (
        "category/electronics/phones"
    )


def test_leading_and_trailing_slashes_are_trimmed():
    assert term_archive_path("tag", "/release/") == "tag/release"
