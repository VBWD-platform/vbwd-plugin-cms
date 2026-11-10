"""S154 P2 — the cms "indexable content type" switches and their precedence.

Four switches decide which cms URL families reach the sitemap:
``seo_index_pages`` (default on), ``seo_index_posts`` (on),
``seo_index_categories`` (off) and ``seo_index_tags`` (off).

Precedence for pages (the only switch with a pre-S154 key): the new key wins
when it is saved; else the legacy ``sitemap_include_pages``; else the default.
"""
import json
import os

import pytest

from plugins.cms.src.services.seo_index_switches import (
    SEO_INDEX_CATEGORIES_KEY,
    SEO_INDEX_PAGES_KEY,
    SEO_INDEX_POSTS_KEY,
    SEO_INDEX_TAGS_KEY,
    SWITCHED_OFF_ROBOTS,
    SeoIndexSwitches,
    index_robots_override,
    post_type_is_indexable,
    resolve_seo_index_switches,
    term_type_is_indexable,
)

_PLUGIN_DIR = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)


def test_defaults_index_pages_and_posts_but_not_term_archives():
    switches = resolve_seo_index_switches({})
    assert switches.pages is True
    assert switches.posts is True
    assert switches.categories is False
    assert switches.tags is False


def test_saved_values_override_the_defaults():
    switches = resolve_seo_index_switches(
        {
            SEO_INDEX_PAGES_KEY: False,
            SEO_INDEX_POSTS_KEY: False,
            SEO_INDEX_CATEGORIES_KEY: True,
            SEO_INDEX_TAGS_KEY: True,
        }
    )
    assert (switches.pages, switches.posts) == (False, False)
    assert (switches.categories, switches.tags) == (True, True)


def test_legacy_include_pages_applies_when_the_new_key_is_not_saved():
    assert resolve_seo_index_switches({"sitemap_include_pages": False}).pages is False


@pytest.mark.parametrize("new_value", [True, False])
def test_new_pages_key_wins_over_the_legacy_key(new_value):
    config = {SEO_INDEX_PAGES_KEY: new_value, "sitemap_include_pages": not new_value}
    assert resolve_seo_index_switches(config).pages is new_value


@pytest.mark.parametrize("key", [SEO_INDEX_PAGES_KEY, SEO_INDEX_TAGS_KEY])
def test_a_null_value_counts_as_not_saved(key):
    defaults = resolve_seo_index_switches({})
    assert resolve_seo_index_switches({key: None}) == defaults


def test_switches_ship_in_config_json_with_their_defaults():
    with open(os.path.join(_PLUGIN_DIR, "config.json")) as config_file:
        schema = json.load(config_file)
    assert schema[SEO_INDEX_PAGES_KEY]["default"] is True
    assert schema[SEO_INDEX_POSTS_KEY]["default"] is True
    assert schema[SEO_INDEX_CATEGORIES_KEY]["default"] is False
    assert schema[SEO_INDEX_TAGS_KEY]["default"] is False
    for key in (
        SEO_INDEX_PAGES_KEY,
        SEO_INDEX_POSTS_KEY,
        SEO_INDEX_CATEGORIES_KEY,
        SEO_INDEX_TAGS_KEY,
    ):
        assert schema[key]["type"] == "boolean"


def test_switches_render_in_the_fe_admin_plugin_settings():
    with open(os.path.join(_PLUGIN_DIR, "admin-config.json")) as admin_file:
        admin_config = json.load(admin_file)
    field_keys = {
        field["key"] for tab in admin_config["tabs"] for field in tab["fields"]
    }
    assert {
        SEO_INDEX_PAGES_KEY,
        SEO_INDEX_POSTS_KEY,
        SEO_INDEX_CATEGORIES_KEY,
        SEO_INDEX_TAGS_KEY,
    } <= field_keys


# ── S154 D7: one rule maps a content type to "indexable" and to its robots ──


def _switches(**overrides):
    values = {"pages": True, "posts": True, "categories": True, "tags": True}
    values.update(overrides)
    return SeoIndexSwitches(**values)


@pytest.mark.parametrize(
    "post_type, switch_name", [("page", "pages"), ("post", "posts")]
)
def test_post_type_follows_its_own_switch(post_type, switch_name):
    assert post_type_is_indexable(_switches(), post_type) is True
    assert post_type_is_indexable(_switches(**{switch_name: False}), post_type) is False


def test_a_post_type_without_a_switch_stays_indexable():
    assert post_type_is_indexable(_switches(pages=False, posts=False), "faq") is True


@pytest.mark.parametrize(
    "term_type, switch_name", [("category", "categories"), ("tag", "tags")]
)
def test_term_type_follows_its_own_switch(term_type, switch_name):
    assert term_type_is_indexable(_switches(), term_type) is True
    assert term_type_is_indexable(_switches(**{switch_name: False}), term_type) is False


def test_hierarchical_term_types_follow_the_categories_switch():
    assert term_type_is_indexable(_switches(categories=False), "topic") is False


def test_robots_override_keeps_the_page_robots_when_indexable():
    assert index_robots_override(search_visible=True, type_indexable=True) is None


def test_switched_off_type_is_noindex_but_still_followed():
    override = index_robots_override(search_visible=True, type_indexable=False)
    assert override == SWITCHED_OFF_ROBOTS == "noindex,follow"


@pytest.mark.parametrize("type_indexable", [True, False])
def test_private_or_excluded_content_wins_with_nofollow(type_indexable):
    override = index_robots_override(
        search_visible=False, type_indexable=type_indexable
    )
    assert override == "noindex,nofollow"
