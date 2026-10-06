"""Integration: the public single-post GET lists translation siblings (S152 W3).

``GET /api/v1/cms/posts/<slug>`` gains a generic field::

    "translations": [{"language": "de", "slug": "...", "url": "..."}]

listing the post's translation siblings — posts sharing its non-null
``translation_group_id`` — with the post itself excluded, ONLY published
siblings, ordered by language. ``url`` is built by the same rule the sitemap
hreflang alternates use, so the two can never disagree. The siblings come from
ONE query (no N+1) shared with the SEO loader, so hreflang also stops pointing
at draft siblings.

Engineering requirements (binding, restated): TDD-first (this RED set);
DevOps-first (real PostgreSQL via the rolled-back ``db`` fixture, cold local +
CI); SOLID/DI/DRY (one sibling query used by SEO and the public route, one URL
rule); Liskov (no group → ``[]``, never a raise); clean code; no
overengineering. Quality guard: ``bin/pre-commit-check.sh --plugin cms --full``.
"""
import re
import uuid

import pytest
from flask import current_app
from sqlalchemy import event

from plugins.cms.src.models.cms_post import (
    POST_STATUS_DRAFT,
    POST_STATUS_PUBLISHED,
)
from plugins.cms.src.repositories.post_repository import PostRepository
from plugins.cms.src.repositories.post_term_repository import PostTermRepository
from plugins.cms.src.repositories.term_repository import TermRepository
from plugins.cms.src.services import post_type_registry
from plugins.cms.src.services.post_service import PostService
from plugins.cms.src.services.post_type_registry import PostType
from plugins.cms.src.services.seo_post_loader import SeoPostLoader
from plugins.cms.src.services.seo_prerender import SeoPrerenderWriter
from plugins.cms.src.services.seo_sitemap_provider import CmsSitemapProvider

PUBLISHED_SIBLING_LANGUAGES = ["de", "ru"]
DRAFT_SIBLING_LANGUAGE = "fr"
SIBLING_QUERY_PATTERN = re.compile(r"cms_post\.translation_group_id\s*=")
PRERENDER_HREFLANG_PATTERN = re.compile(
    r'<link rel="alternate" hreflang="([^"]+)" href="([^"]+)"'
)


@pytest.fixture(autouse=True)
def _registries():
    post_type_registry.register_post_type(
        PostType(key="post", label="Post", routable=True, hierarchical=False)
    )
    yield


def _post_service(db):
    return PostService(
        repo=PostRepository(db.session),
        term_repo=TermRepository(db.session),
        post_term_repo=PostTermRepository(db.session),
        event_dispatcher=None,
    )


def _create_member(post_service, marker, language, status, group_id):
    return post_service.create_post(
        {
            "type": "post",
            "title": f"Translations {language} {marker}",
            "slug": f"translations-{language}-{marker}",
            "status": status,
            "language": language,
            "translation_group_id": group_id,
        }
    )


@pytest.fixture
def translation_group(db):
    """An en post with published de + ru siblings and a draft fr sibling."""
    marker = uuid.uuid4().hex[:8]
    group_id = str(uuid.uuid4())
    post_service = _post_service(db)
    members = {
        language: _create_member(
            post_service, marker, language, POST_STATUS_PUBLISHED, group_id
        )
        for language in ["en", *PUBLISHED_SIBLING_LANGUAGES]
    }
    members[DRAFT_SIBLING_LANGUAGE] = _create_member(
        post_service, marker, DRAFT_SIBLING_LANGUAGE, POST_STATUS_DRAFT, group_id
    )
    return {"marker": marker, "members": members}


def _get_public_post(client, slug, query=""):
    response = client.get(f"/api/v1/cms/posts/{slug}?type=post{query}")
    assert response.status_code == 200, response.get_json()
    return response.get_json()


def _sitemap_hrefs_by_language(db, marker):
    """The hreflang hrefs the SEO sitemap builder emits for the group."""
    provider = CmsSitemapProvider(
        post_loader=SeoPostLoader(db.session),
        public_base_url_provider=lambda: (
            current_app.config_store.get_config("cms") or {}
        ).get("public_base_url", ""),
    )
    return {
        alternate["hreflang"]: alternate["href"]
        for entry in provider.sitemap_entries()
        for alternate in entry.alternates
        if marker in alternate["href"]
    }


def test_lists_published_siblings_only_ordered_by_language(
    app, db, client, translation_group
):
    members = translation_group["members"]

    payload = _get_public_post(client, members["en"]["slug"])

    assert [item["language"] for item in payload["translations"]] == (
        PUBLISHED_SIBLING_LANGUAGES
    )
    assert [item["slug"] for item in payload["translations"]] == [
        members[language]["slug"] for language in PUBLISHED_SIBLING_LANGUAGES
    ]


def test_post_without_translation_group_has_empty_translations(app, db, client):
    marker = uuid.uuid4().hex[:8]
    post = _post_service(db).create_post(
        {
            "type": "post",
            "title": f"Lonely {marker}",
            "slug": f"lonely-{marker}",
            "status": POST_STATUS_PUBLISHED,
        }
    )

    assert _get_public_post(client, post["slug"])["translations"] == []


def test_post_itself_is_excluded(app, db, client, translation_group):
    members = translation_group["members"]

    payload = _get_public_post(client, members["de"]["slug"])

    assert [item["language"] for item in payload["translations"]] == ["en", "ru"]
    assert members["de"]["slug"] not in [
        item["slug"] for item in payload["translations"]
    ]


def test_url_equals_the_sitemap_hreflang_href(app, db, client, translation_group):
    members = translation_group["members"]
    hrefs_by_language = _sitemap_hrefs_by_language(db, translation_group["marker"])

    payload = _get_public_post(client, members["en"]["slug"])

    assert payload["translations"], "translations must be non-empty to compare"
    for item in payload["translations"]:
        assert item["url"] == hrefs_by_language[item["language"]]
    assert DRAFT_SIBLING_LANGUAGE not in hrefs_by_language


def test_siblings_are_loaded_in_one_query(app, db, client, translation_group):
    engine = db.session.get_bind()
    sibling_statements = []

    def _record(conn, cursor, statement, parameters, context, executemany):
        if SIBLING_QUERY_PATTERN.search(statement):
            sibling_statements.append(statement)

    event.listen(engine, "before_cursor_execute", _record)
    try:
        _get_public_post(client, translation_group["members"]["en"]["slug"])
    finally:
        event.remove(engine, "before_cursor_execute", _record)

    assert len(sibling_statements) == 1


def test_draft_preview_lists_published_siblings_only(
    app, db, client, translation_group
):
    draft = translation_group["members"][DRAFT_SIBLING_LANGUAGE]

    payload = _get_public_post(
        client, draft["slug"], f"&preview_token={draft['preview_token']}"
    )

    assert payload["id"] == draft["id"]
    assert [item["language"] for item in payload["translations"]] == [
        "de",
        "en",
        "ru",
    ]
    assert all("preview_token" not in item for item in payload["translations"])


def _prerender_hrefs_by_language(db, tmp_path, post):
    """The hreflang hrefs the cms prerender head emits for one post."""
    writer = SeoPrerenderWriter(
        var_dir=str(tmp_path),
        post_loader=SeoPostLoader(db.session),
        public_base_url=_public_base_url(),
    )
    writer.handle_content_changed(
        {"post_id": post["id"], "slug": post["slug"], "status": post["status"]}
    )
    html = (tmp_path / "seo" / f"{post['slug']}.html").read_text(encoding="utf-8")
    return dict(PRERENDER_HREFLANG_PATTERN.findall(html))


def _public_base_url():
    return (current_app.config_store.get_config("cms") or {}).get("public_base_url", "")


def test_prerender_sitemap_and_public_translations_agree(app, db, client, tmp_path):
    """S152 W3b: a sibling WITHOUT a stored canonical_url is not dropped from
    the prerender head — prerender, sitemap and public translations (+ self)
    all list the same alternates; an explicit canonical_url stays verbatim and
    a draft sibling is in none of them."""
    marker = uuid.uuid4().hex[:8]
    group_id = str(uuid.uuid4())
    post_service = _post_service(db)
    english = _create_member(
        post_service, marker, "en", POST_STATUS_PUBLISHED, group_id
    )
    _create_member(post_service, marker, "de", POST_STATUS_PUBLISHED, group_id)
    explicit_canonical_url = f"https://elsewhere.example/ru-{marker}"
    post_service.create_post(
        {
            "type": "post",
            "title": f"Translations ru {marker}",
            "slug": f"translations-ru-{marker}",
            "status": POST_STATUS_PUBLISHED,
            "language": "ru",
            "translation_group_id": group_id,
            "canonical_url": explicit_canonical_url,
        }
    )
    _create_member(
        post_service, marker, DRAFT_SIBLING_LANGUAGE, POST_STATUS_DRAFT, group_id
    )

    prerender_hrefs = _prerender_hrefs_by_language(db, tmp_path, english)
    sitemap_hrefs = _sitemap_hrefs_by_language(db, marker)
    payload = _get_public_post(client, english["slug"])
    public_hrefs = {"en": prerender_hrefs["en"]}
    public_hrefs.update(
        {item["language"]: item["url"] for item in payload["translations"]}
    )

    prerender_alternates = {
        language: href
        for language, href in prerender_hrefs.items()
        if language != "x-default"
    }
    assert sorted(prerender_alternates) == ["de", "en", "ru"]
    assert prerender_hrefs["ru"] == explicit_canonical_url
    assert prerender_hrefs["x-default"] == prerender_hrefs["en"]
    assert prerender_alternates == public_hrefs
    assert {
        language: href
        for language, href in sitemap_hrefs.items()
        if language != "x-default"
    } == prerender_alternates
