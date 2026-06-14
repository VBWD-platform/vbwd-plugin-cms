"""S52.8 — integration: POST /api/v1/cms/api/posts via the core API-key guard.

A real core ``ApiKey`` scoped ``cms:posts:create`` ingests a post (and a page)
authored as the key's user, persisting terms + image. Missing scope → 403; no
key → 401. Data is created through services/repos (no raw SQL).
"""
import base64

import pytest

from vbwd.models.user import User
from vbwd.repositories.api_key_repository import ApiKeyRepository
from vbwd.services.api_key_service import ApiKeyService
from plugins.cms.src.repositories.post_repository import PostRepository
from plugins.cms.src.repositories.term_repository import TermRepository
from plugins.cms.src.services import post_type_registry, term_type_registry
from plugins.cms.src.services.post_type_registry import PostType
from plugins.cms.src.services.term_type_registry import TermType


@pytest.fixture(autouse=True)
def _registry():
    post_type_registry.clear_post_types()
    post_type_registry.register_post_type(
        PostType(key="page", label="Page", routable=True, hierarchical=True)
    )
    post_type_registry.register_post_type(
        PostType(key="post", label="Post", routable=True, hierarchical=False)
    )
    term_type_registry.clear_term_types()
    term_type_registry.register_term_type(
        TermType(key="category", label="Category", hierarchical=True)
    )
    # ``tag`` is no longer a cms_term taxonomy (D7) — ingested tags go to the
    # core tag catalog via the tags port.
    yield
    post_type_registry.clear_post_types()
    term_type_registry.clear_term_types()


def _make_key(db, scopes):
    user = db.session.query(User).filter_by(email="test@example.com").first()
    assert user is not None, "seeded test user missing"
    service = ApiKeyService(ApiKeyRepository(db.session))
    _, plaintext = service.generate(user_id=user.id, label="ingest test", scopes=scopes)
    return user, plaintext


_PNG = base64.b64encode(b"\x89PNG\r\n\x1a\n-fake").decode()


def test_no_key_returns_401(client, db):
    response = client.post("/api/v1/cms/api/posts", json={"title": "X"})
    assert response.status_code == 401


def test_key_without_scope_returns_403(client, db):
    _, plaintext = _make_key(db, scopes=["other:scope"])
    response = client.post(
        "/api/v1/cms/api/posts",
        json={"title": "X"},
        headers={"X-API-Key": plaintext},
    )
    assert response.status_code == 403


def test_scoped_key_creates_post_with_terms_and_image(client, db):
    user, plaintext = _make_key(db, scopes=["cms:posts:create"])
    payload = {
        "title": "Ingested headline",
        "categories": ["News"],
        "tags": ["saas"],
        "source_css": ".x{}",
        "seo": {"meta_title": "MT", "robots": "index,follow"},
        "image": {"base64": _PNG, "filename": "hero.png", "mime_type": "image/png"},
    }
    response = client.post(
        "/api/v1/cms/api/posts",
        json=payload,
        headers={"X-API-Key": plaintext},
    )
    assert response.status_code == 201, response.get_data(as_text=True)
    body = response.get_json()
    assert body["type"] == "post"
    assert body["status"] == "draft"
    assert body["featured_image_url"]

    post = PostRepository(db.session).find_by_id(body["id"])
    assert post is not None
    assert str(post.author_id) == str(user.id)
    assert post.source_css == ".x{}"
    assert post.meta_title == "MT"

    # D7: the category stays on the cms_term taxonomy; the tag goes to the core
    # catalog (vbwd_entity_tag on cms_post), NOT a cms_term('tag') row.
    terms = TermRepository(db.session)
    assert terms.find_by_type_and_slug("category", "news") is not None
    assert terms.find_by_type_and_slug("tag", "saas") is None

    from uuid import UUID

    from vbwd.services.tags_and_custom_fields import resolve_tags_and_custom_fields

    core_tags = resolve_tags_and_custom_fields().get_tags(
        "cms_post", UUID(str(post.id))
    )
    assert "saas" in core_tags


def test_scoped_key_creates_page(client, db):
    _, plaintext = _make_key(db, scopes=["cms:posts:create"])
    response = client.post(
        "/api/v1/cms/api/posts",
        json={"title": "About us", "type": "page"},
        headers={"X-API-Key": plaintext},
    )
    assert response.status_code == 201, response.get_data(as_text=True)
    assert response.get_json()["type"] == "page"
