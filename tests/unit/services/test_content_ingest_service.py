"""S52.8 — unit tests for the cms ContentIngestService (MagicMock collaborators).

The service OWNS NO persistence — it composes PostService.create_post,
TermService find-or-create, and CmsImageService.upload_image. ``author_id`` is
the key's user; status defaults to ``draft``; bad payloads raise so the route
answers 400.
"""
import base64
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from plugins.cms.src.services.content_ingest_service import ContentIngestService

POST_ID = str(uuid4())


def _make_service():
    post_service = MagicMock()
    term_service = MagicMock()
    image_service = MagicMock()
    tags_port = MagicMock()

    created = {"id": POST_ID, "slug": "my-headline", "type": "post", "status": "draft"}
    post_service.create_post.return_value = created
    # find_or_create returns a term dict keyed by name (deterministic id per name).
    term_service.find_or_create.side_effect = lambda term_type, name: {
        "id": f"{term_type}:{name}"
    }
    image_service.upload_image.return_value = {"url_path": "/uploads/images/hero.jpg"}

    service = ContentIngestService(
        post_service=post_service,
        term_service=term_service,
        image_service=image_service,
        tags_port=tags_port,
    )
    return service, post_service, term_service, image_service, tags_port


def test_title_required():
    service, *_ = _make_service()
    with pytest.raises(ValueError):
        service.ingest({"type": "post"}, user_id="user-1")


def test_creates_post_with_author_and_default_status():
    service, post_service, *_ = _make_service()

    service.ingest({"title": "My headline"}, user_id="user-1")

    data = post_service.create_post.call_args[0][0]
    assert data["title"] == "My headline"
    assert data["author_id"] == "user-1"
    assert data["status"] == "draft"
    assert data["type"] == "post"


def test_type_page_supported_and_status_override():
    service, post_service, *_ = _make_service()

    service.ingest(
        {"title": "About", "type": "page", "status": "published"}, user_id="u"
    )

    data = post_service.create_post.call_args[0][0]
    assert data["type"] == "page"
    assert data["status"] == "published"


def test_categories_via_terms_and_tags_via_core_port():
    """D7: categories stay on the cms_term taxonomy (find_or_create('category')
    + assign_terms); tags go to the core tags port (set_tags on cms_post),
    NOT find_or_create('tag')."""
    service, post_service, term_service, _, tags_port = _make_service()

    service.ingest(
        {"title": "T", "categories": ["News", "Tech"], "tags": ["SaaS", "Dev Ops"]},
        user_id="u",
    )

    # Categories — still find-or-create('category') + assign_terms.
    calls = {(c.args[0], c.args[1]) for c in term_service.find_or_create.call_args_list}
    assert ("category", "News") in calls
    assert ("category", "Tech") in calls
    # No tag term is created on the cms_term taxonomy any more.
    assert all(c.args[0] != "tag" for c in term_service.find_or_create.call_args_list)
    term_ids = post_service.assign_terms.call_args[0][1]
    assert set(term_ids) == {"category:News", "category:Tech"}

    # Tags — routed to the core port as cms_post-scoped slugs (slugified names).
    tags_port.set_tags.assert_called_once()
    entity_type, entity_id, slugs = tags_port.set_tags.call_args[0]
    assert entity_type == "cms_post"
    assert str(entity_id) == POST_ID
    assert slugs == ["saas", "dev-ops"]


def test_no_tags_does_not_call_set_tags():
    service, _, _, _, tags_port = _make_service()

    service.ingest({"title": "T", "categories": ["News"]}, user_id="u")

    tags_port.set_tags.assert_not_called()


def test_image_base64_uploaded_and_mapped_to_featured_image():
    service, post_service, _, image_service, _ = _make_service()
    raw = b"fake-bytes"
    encoded = base64.b64encode(raw).decode()

    service.ingest(
        {
            "title": "T",
            "image": {
                "base64": encoded,
                "filename": "hero.jpg",
                "mime_type": "image/jpeg",
            },
        },
        user_id="u",
    )

    file_data = image_service.upload_image.call_args.kwargs.get("file_data")
    if file_data is None:
        file_data = image_service.upload_image.call_args[0][0]
    assert file_data == raw
    data = post_service.create_post.call_args[0][0]
    assert data["featured_image_url"] == "/uploads/images/hero.jpg"


def test_image_data_url_prefix_tolerated():
    service, post_service, _, image_service, _ = _make_service()
    raw = b"abc"
    data_url = "data:image/png;base64," + base64.b64encode(raw).decode()

    service.ingest(
        {"title": "T", "image": {"base64": data_url, "filename": "x.png"}},
        user_id="u",
    )

    file_data = image_service.upload_image.call_args.kwargs.get("file_data")
    if file_data is None:
        file_data = image_service.upload_image.call_args[0][0]
    assert file_data == raw


def test_bad_base64_raises_value_error():
    service, *_ = _make_service()
    with pytest.raises(ValueError):
        service.ingest(
            {"title": "T", "image": {"base64": "!!!not-base64!!!", "filename": "x"}},
            user_id="u",
        )


def test_seo_fields_and_source_css_carried():
    service, post_service, *_ = _make_service()

    service.ingest(
        {
            "title": "T",
            "source_css": ".x{}",
            "excerpt": "hi",
            "content_html": "<p>hi</p>",
            "seo": {
                "meta_title": "MT",
                "meta_description": "MD",
                "og_image_url": "/og.png",
                "canonical_url": "https://x/y",
                "robots": "index,follow",
            },
        },
        user_id="u",
    )

    data = post_service.create_post.call_args[0][0]
    assert data["source_css"] == ".x{}"
    assert data["excerpt"] == "hi"
    assert data["content_html"] == "<p>hi</p>"
    assert data["meta_title"] == "MT"
    assert data["meta_description"] == "MD"
    assert data["og_image_url"] == "/og.png"
    assert data["canonical_url"] == "https://x/y"
    assert data["robots"] == "index,follow"


def test_returns_response_shape():
    service, *_ = _make_service()
    result = service.ingest({"title": "My headline"}, user_id="u")
    assert result["id"] == POST_ID
    assert result["slug"] == "my-headline"
    assert result["type"] == "post"
    assert result["status"] == "draft"
