"""Unit: PostService lists a post's public translation siblings (S152 W3).

The public single-post payload gains ``translations: [{language, slug, url}]``.
The siblings come from ONE repository query (published members of the same
``translation_group_id``, the post itself excluded, ordered by language) and
each ``url`` is built by the shared ``derive_canonical_url`` rule — the same
rule the sitemap hreflang alternates use (DRY).

Engineering requirements (binding, restated): TDD-first (this RED set); DI
(repo injected); DRY (one sibling query, one URL rule); Liskov (no group → a
clean ``[]``, never a raise); clean code; no overengineering. Quality guard:
``bin/pre-commit-check.sh --plugin cms --full``.
"""
from uuid import uuid4
from unittest.mock import MagicMock

from plugins.cms.src.models.cms_post import CmsPost
from plugins.cms.src.services.post_service import PostService

PUBLIC_BASE_URL = "https://example.test"


def _sibling(language, slug, canonical_url=None):
    sibling = CmsPost()
    sibling.id = uuid4()
    sibling.language = language
    sibling.slug = slug
    sibling.canonical_url = canonical_url
    return sibling


def _service(repo):
    return PostService(
        repo=repo,
        term_repo=MagicMock(),
        post_term_repo=MagicMock(),
        permalink_config={"public_base_url": PUBLIC_BASE_URL},
    )


def test_no_translation_group_returns_empty_list_without_querying():
    repo = MagicMock()

    translations = _service(repo).list_public_translations(
        {"id": str(uuid4()), "translation_group_id": None}
    )

    assert translations == []
    repo.find_published_translation_siblings.assert_not_called()


def test_siblings_map_to_language_slug_and_canonical_url():
    repo = MagicMock()
    repo.find_published_translation_siblings.return_value = [
        _sibling("de", "ueber-uns"),
        _sibling("ru", "o-nas", canonical_url="https://ru.example.test/o-nas"),
    ]
    post_id = str(uuid4())
    group_id = str(uuid4())

    translations = _service(repo).list_public_translations(
        {"id": post_id, "translation_group_id": group_id}
    )

    repo.find_published_translation_siblings.assert_called_once_with(group_id, post_id)
    assert translations == [
        {
            "language": "de",
            "slug": "ueber-uns",
            "url": f"{PUBLIC_BASE_URL}/ueber-uns",
        },
        {
            "language": "ru",
            "slug": "o-nas",
            "url": "https://ru.example.test/o-nas",
        },
    ]
