"""Unit tests for PermalinkRenderer (S122) — pure config→path transform.

The renderer is side-effect-free: given a mode, the cms config, a post's own
``slug_base``, its primary category ancestor chain, the publish timestamp and
the post id, it returns the full lookup path (no leading/trailing slash). No DB,
no Flask, no clock dependency beyond the documented ``published_at is None``
fallback.

Engineering requirements (binding, restated): TDD-first; DevOps-first; SOLID/
DI/DRY (the structured mode is literally rendered through the SAME template
engine, so "structured == equivalent template" is proven, not asserted by
inspection); Liskov (a missing primary → the configured uncategorized segment,
never a crash); clean code; no overengineering. Quality guard:
``bin/pre-commit-check.sh --plugin cms --full``.
"""
from datetime import datetime, timezone

from plugins.cms.src.services.permalink import (
    PermalinkRenderer,
    PrimaryCategory,
    PERMALINK_MODE_STRUCTURED,
    PERMALINK_MODE_TEMPLATE,
)


PUBLISHED = datetime(2026, 7, 7, 15, 30, 0, tzinfo=timezone.utc)


def _config(**overrides):
    base = {
        "posts_root": "blog",
        "posts_permalink_include_year": False,
        "posts_permalink_uncategorized_slug": "uncategorized",
        "posts_permalink_template": "%root%/%category%/%slug%",
    }
    base.update(overrides)
    return base


def _render(
    mode,
    config,
    *,
    slug_base="my-post",
    primary=None,
    published_at=PUBLISHED,
    post_id="11111111-1111-1111-1111-111111111111",
):
    return PermalinkRenderer().render(
        mode,
        config,
        slug_base=slug_base,
        primary_term=primary,
        published_at=published_at,
        post_id=post_id,
    )


class TestTokens:
    def test_root_and_slug(self):
        result = _render(
            PERMALINK_MODE_TEMPLATE, _config(posts_permalink_template="%root%/%slug%")
        )
        assert result == "blog/my-post"

    def test_top_level_category_tokens(self):
        primary = PrimaryCategory(ancestor_slugs=("electronics",))
        cfg = _config(
            posts_permalink_template="%category%/%subcategory%/%category_path%/%slug%"
        )
        # subcategory is empty for a top-level primary (its segment collapses).
        assert _render(PERMALINK_MODE_TEMPLATE, cfg, primary=primary) == (
            "electronics/electronics/my-post"
        )

    def test_nested_category_tokens(self):
        primary = PrimaryCategory(ancestor_slugs=("electronics", "phones", "foldables"))
        cfg = _config(
            posts_permalink_template="%category%/%subcategory%/%category_path%"
        )
        assert _render(PERMALINK_MODE_TEMPLATE, cfg, primary=primary) == (
            "electronics/foldables/electronics/phones/foldables"
        )

    def test_date_tokens_zero_padded(self):
        cfg = _config(posts_permalink_template="%year%/%month%/%day%/%slug%")
        published = datetime(2026, 3, 4, 9, 5, 0, tzinfo=timezone.utc)
        assert _render(PERMALINK_MODE_TEMPLATE, cfg, published_at=published) == (
            "2026/03/04/my-post"
        )

    def test_timestamp_tokens_are_equivalent(self):
        cfg_a = _config(posts_permalink_template="%slug%-%timestamp%")
        cfg_b = _config(posts_permalink_template="%slug%-%YYYYMMDDHHmmss%")
        assert _render(PERMALINK_MODE_TEMPLATE, cfg_a) == "my-post-20260707153000"
        assert _render(PERMALINK_MODE_TEMPLATE, cfg_b) == "my-post-20260707153000"

    def test_id_token(self):
        cfg = _config(posts_permalink_template="%slug%/%id%")
        assert (
            _render(PERMALINK_MODE_TEMPLATE, cfg, post_id="abc-123")
            == "my-post/abc-123"
        )


class TestRules:
    def test_empty_token_collapses_no_double_slash(self):
        # A top-level primary → %subcategory% resolves to "" → its segment drops.
        primary = PrimaryCategory(ancestor_slugs=("electronics",))
        cfg = _config(posts_permalink_template="%root%/%subcategory%/%slug%")
        assert _render(PERMALINK_MODE_TEMPLATE, cfg, primary=primary) == "blog/my-post"

    def test_no_primary_uses_uncategorized(self):
        cfg = _config(posts_permalink_template="%root%/%category_path%/%slug%")
        assert _render(PERMALINK_MODE_TEMPLATE, cfg, primary=None) == (
            "blog/uncategorized/my-post"
        )

    def test_no_primary_custom_uncategorized_slug(self):
        cfg = _config(
            posts_permalink_template="%root%/%category_path%/%slug%",
            posts_permalink_uncategorized_slug="misc",
        )
        assert (
            _render(PERMALINK_MODE_TEMPLATE, cfg, primary=None) == "blog/misc/my-post"
        )

    def test_literal_text_passed_through_slug_safe(self):
        cfg = _config(posts_permalink_template="Abraca Dabra/%slug%")
        assert _render(PERMALINK_MODE_TEMPLATE, cfg) == "abraca-dabra/my-post"

    def test_segments_are_slugified(self):
        cfg = _config(posts_permalink_template="%root%/%slug%")
        assert _render(PERMALINK_MODE_TEMPLATE, cfg, slug_base="Hello World!") == (
            "blog/hello-world"
        )

    def test_result_has_no_leading_or_trailing_slash(self):
        cfg = _config(posts_permalink_template="/%root%/%slug%/")
        assert _render(PERMALINK_MODE_TEMPLATE, cfg) == "blog/my-post"

    def test_none_published_at_falls_back_to_now(self):
        cfg = _config(posts_permalink_template="%year%/%slug%")
        result = _render(PERMALINK_MODE_TEMPLATE, cfg, published_at=None)
        current_year = f"{datetime.now(timezone.utc).year:04d}"
        assert result == f"{current_year}/my-post"


class TestStructuredMode:
    def test_structured_equals_equivalent_template(self):
        primary = PrimaryCategory(ancestor_slugs=("electronics", "phones"))
        cfg = _config(posts_root="blog", posts_permalink_include_year=True)
        structured = _render(PERMALINK_MODE_STRUCTURED, cfg, primary=primary)
        equivalent = _render(
            PERMALINK_MODE_TEMPLATE,
            _config(posts_permalink_template="%root%/%year%/%category_path%/%slug%"),
            primary=primary,
        )
        assert structured == equivalent
        assert structured == "blog/2026/electronics/phones/my-post"

    def test_structured_without_year(self):
        primary = PrimaryCategory(ancestor_slugs=("electronics",))
        cfg = _config(posts_root="blog", posts_permalink_include_year=False)
        assert _render(PERMALINK_MODE_STRUCTURED, cfg, primary=primary) == (
            "blog/electronics/my-post"
        )

    def test_structured_no_primary_has_uncategorized_segment(self):
        cfg = _config(posts_root="blog", posts_permalink_include_year=False)
        assert _render(PERMALINK_MODE_STRUCTURED, cfg, primary=None) == (
            "blog/uncategorized/my-post"
        )


class TestFullExampleTemplate:
    def test_users_example_template_renders_exactly(self):
        # abracadabra/%subcategory%/anotherabracadabra/%year%/%slug%-%timestamp%-%category%
        primary = PrimaryCategory(ancestor_slugs=("electronics", "phones"))
        cfg = _config(
            posts_permalink_template=(
                "abracadabra/%subcategory%/anotherabracadabra/%year%/"
                "%slug%-%timestamp%-%category%"
            )
        )
        assert _render(PERMALINK_MODE_TEMPLATE, cfg, primary=primary) == (
            "abracadabra/phones/anotherabracadabra/2026/"
            "my-post-20260707153000-electronics"
        )
