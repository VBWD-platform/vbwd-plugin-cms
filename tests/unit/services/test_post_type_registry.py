"""Unit tests for the post-type registry (S47.0).

The registry is the OCP seam that lets other plugins add post types with
zero cms change. Built-ins (`page`, `post`) are registered by the plugin;
tests register/clear their own to stay isolated.
"""
import pytest
from plugins.cms.src.services.post_type_registry import (
    PostType,
    register_post_type,
    get_post_type,
    list_post_types,
    is_registered,
    clear_post_types,
)


@pytest.fixture(autouse=True)
def _clean_registry():
    clear_post_types()
    yield
    clear_post_types()


class TestRegisterPostType:
    def test_register_then_list_includes_it(self):
        register_post_type(PostType(key="page", label="Page", routable=True))
        keys = [post_type.key for post_type in list_post_types()]
        assert "page" in keys

    def test_register_is_idempotent_on_key(self):
        register_post_type(PostType(key="post", label="Post", routable=True))
        register_post_type(PostType(key="post", label="Article", routable=True))
        matches = [pt for pt in list_post_types() if pt.key == "post"]
        assert len(matches) == 1
        assert matches[0].label == "Article"

    def test_hierarchical_flag_defaults_false(self):
        register_post_type(PostType(key="post", label="Post", routable=True))
        assert get_post_type("post").hierarchical is False

    def test_hierarchical_flag_preserved(self):
        register_post_type(
            PostType(key="page", label="Page", routable=True, hierarchical=True)
        )
        assert get_post_type("page").hierarchical is True

    def test_default_template_preserved(self):
        register_post_type(
            PostType(
                key="page",
                label="Page",
                routable=True,
                default_template="content-page",
            )
        )
        assert get_post_type("page").default_template == "content-page"


class TestLookup:
    def test_is_registered_true_for_known(self):
        register_post_type(PostType(key="page", label="Page", routable=True))
        assert is_registered("page") is True

    def test_is_registered_false_for_unknown(self):
        assert is_registered("event") is False

    def test_get_unknown_returns_none(self):
        assert get_post_type("event") is None
