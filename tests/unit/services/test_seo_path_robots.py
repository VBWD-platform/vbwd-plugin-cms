"""S154 D7 — the robots a public cms PATH must carry (``/_seo-render``).

The on-demand render captures the SPA, which knows nothing about the per-type
indexable switches, so the route asks ``SeoPathRobots`` for the override. The
path resolves like the fe catch-all (page → post → ``category/`` / ``tag/``
term archive): a switched-off type answers ``noindex,follow``; private or
excluded content answers ``noindex,nofollow``; anything else (indexable, or a
path cms does not own) answers ``None`` — the render is served unchanged.

Engineering requirements (binding, restated): TDD-first; SOLID/DI (loader and
switches injected); DRY (the same ``index_robots_override`` the writer uses);
Liskov (an unknown path is ``None``, never an error); clean code; no
overengineering. Guard: ``bin/pre-commit-check.sh --plugin cms --full``.
"""
import pytest

from plugins.cms.src.models.cms_post import POST_STATUS_PUBLISHED
from plugins.cms.src.services.seo_index_switches import SeoIndexSwitches
from plugins.cms.src.services.seo_path_robots import SeoPathRobots

_PRIVATE_PREFIXES = ("/dashboard",)


class _Post:
    def __init__(self, slug, post_type="page", seo_excluded=False):
        self.slug = slug
        self.type = post_type
        self.status = POST_STATUS_PUBLISHED
        self.seo_excluded = seo_excluded
        self.robots = "index,follow"


class _Loader:
    def __init__(self, posts):
        self._posts = {post.slug: post for post in posts}
        self.looked_up = []

    def find_published_by_path(self, slug):
        self.looked_up.append(slug)
        return self._posts.get(slug)

    def terms_for(self, post):
        return []


def _switches(**overrides):
    values = {"pages": True, "posts": True, "categories": True, "tags": True}
    values.update(overrides)
    return SeoIndexSwitches(**values)


def _robots(path, stored_posts=(), home_slug="index", **switch_overrides):
    return SeoPathRobots(
        _Loader(list(stored_posts)),
        _switches(**switch_overrides),
        _PRIVATE_PREFIXES,
        home_slug,
    ).robots_for(path)


def test_switched_off_page_is_noindex_follow():
    assert _robots("/about", [_Post("about")], pages=False) == "noindex,follow"


def test_switched_off_post_is_noindex_follow():
    news = _Post("blog/news", post_type="post")
    assert _robots("/blog/news/", [news], posts=False) == "noindex,follow"


def test_indexable_page_keeps_the_render():
    assert _robots("/about", [_Post("about")]) is None


def test_excluded_page_is_noindex_nofollow():
    excluded = _Post("about", seo_excluded=True)
    assert _robots("/about", [excluded], pages=False) == "noindex,nofollow"


def test_root_path_resolves_the_home_slug():
    assert _robots("/", [_Post("index")], pages=False) == "noindex,follow"


@pytest.mark.parametrize(
    "path, switch_name",
    [("/category/guides", "categories"), ("/tag/python", "tags")],
)
def test_switched_off_term_archive_is_noindex_follow(path, switch_name):
    assert _robots(path, **{switch_name: False}) == "noindex,follow"
    assert _robots(path) is None


def test_a_page_wins_over_the_term_archive_pattern():
    page = _Post("category/guides")
    assert _robots("/category/guides", [page], categories=False) is None


def test_a_path_cms_does_not_own_keeps_the_render():
    assert _robots("/shop/product/widget?x=1", pages=False, posts=False) is None
