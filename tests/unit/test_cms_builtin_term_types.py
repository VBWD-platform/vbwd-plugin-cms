"""CMS built-in term types — ``category`` AND ``tag`` (S77 reversal).

The S77 fold-tags decision unregistered the ``tag`` term type so tags lived in
the core ``vbwd_tag`` catalog. That decision is reversed: CMS tags belong to the
CMS taxonomy system (``cms_term``, ``term_type='tag'``), so the plugin must
register BOTH built-in taxonomies again. This restores the Tags tab on
/admin/cms/taxonomy (the tabs come from the term-type registry) and lets the
post editor edit tags as ``cms_term``.

Engineering requirements (binding, restated): TDD-first (this asserts the
contract before/around the change); SOLID/OCP (registration via the term-type
registry seam — no core edit); clean code; no overengineering. Quality guard:
``bin/pre-commit-check.sh --plugin cms --full``.
"""
import pytest

from plugins.cms import CmsPlugin
from plugins.cms.src.services.term_type_registry import (
    clear_term_types,
    list_term_types,
)
from plugins.cms.src.services.post_type_registry import clear_post_types


@pytest.fixture(autouse=True)
def _clean_registries():
    clear_post_types()
    clear_term_types()
    yield
    clear_post_types()
    clear_term_types()


def test_registers_both_category_and_tag_term_types():
    CmsPlugin()._register_built_in_types()

    registered = {term_type.key: term_type for term_type in list_term_types()}
    assert "category" in registered
    assert "tag" in registered


def test_category_is_hierarchical_and_tag_is_flat():
    CmsPlugin()._register_built_in_types()

    registered = {term_type.key: term_type for term_type in list_term_types()}
    assert registered["category"].hierarchical is True
    assert registered["tag"].hierarchical is False
    assert registered["tag"].label == "Tag"
