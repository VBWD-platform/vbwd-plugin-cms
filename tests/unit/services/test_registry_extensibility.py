"""Extensibility oracle (S47.0) — another plugin extends cms with zero edits.

A second plugin registering a custom post-type / term-type must appear in
the registry listings, proving the OCP seam. cms code is never touched.
"""
import pytest

from plugins.cms.src.services.post_type_registry import (
    PostType,
    register_post_type,
    list_post_types,
    clear_post_types,
)
from plugins.cms.src.services.term_type_registry import (
    TermType,
    register_term_type,
    list_term_types,
    clear_term_types,
)


@pytest.fixture(autouse=True)
def _clean():
    clear_post_types()
    clear_term_types()
    yield
    clear_post_types()
    clear_term_types()


def test_external_plugin_post_type_appears():
    register_post_type(PostType(key="event", label="Event", routable=True))
    assert "event" in [post_type.key for post_type in list_post_types()]


def test_external_plugin_term_type_appears():
    register_term_type(TermType(key="series", label="Series", hierarchical=False))
    assert "series" in [term_type.key for term_type in list_term_types()]
