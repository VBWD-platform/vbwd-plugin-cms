"""Unit tests for the term-type registry (S47.0)."""
import pytest
from plugins.cms.src.services.term_type_registry import (
    TermType,
    register_term_type,
    get_term_type,
    list_term_types,
    is_registered,
    clear_term_types,
)


@pytest.fixture(autouse=True)
def _clean_registry():
    clear_term_types()
    yield
    clear_term_types()


class TestRegisterTermType:
    def test_register_then_list_includes_it(self):
        register_term_type(
            TermType(key="category", label="Category", hierarchical=True)
        )
        keys = [term_type.key for term_type in list_term_types()]
        assert "category" in keys

    def test_register_is_idempotent_on_key(self):
        register_term_type(TermType(key="tag", label="Tag", hierarchical=False))
        register_term_type(TermType(key="tag", label="Label", hierarchical=False))
        matches = [tt for tt in list_term_types() if tt.key == "tag"]
        assert len(matches) == 1
        assert matches[0].label == "Label"

    def test_hierarchical_flag_preserved(self):
        register_term_type(
            TermType(key="category", label="Category", hierarchical=True)
        )
        register_term_type(TermType(key="tag", label="Tag", hierarchical=False))
        assert get_term_type("category").hierarchical is True
        assert get_term_type("tag").hierarchical is False


class TestLookup:
    def test_is_registered(self):
        register_term_type(TermType(key="tag", label="Tag", hierarchical=False))
        assert is_registered("tag") is True
        assert is_registered("series") is False

    def test_get_unknown_returns_none(self):
        assert get_term_type("series") is None
