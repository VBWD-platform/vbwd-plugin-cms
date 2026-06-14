"""S77 — CMS registers cms_page/cms_post and appends core tags + custom fields.

The new core tags / custom-fields blocks are added ALONGSIDE the existing CMS
``terms`` taxonomy (categories + legacy tag terms) — they do not touch it (the
D7 ``cms_term('tag')`` migration is a separate later slice). The public post
serializer (``GET /api/v1/cms/posts/<slug>?type=``) appends ``tags`` /
``custom_fields`` keyed by the post's ``type`` (page → ``cms_page``, otherwise
``cms_post``), so the fe-user render + fe-admin editor can read them.
"""
import pytest

from vbwd.services.entity_type_registry import get_entity_type, is_registered


@pytest.mark.parametrize(
    "entity_type,manage_permission",
    [
        ("cms_page", "cms.pages.manage"),
        ("cms_post", "cms.manage"),
    ],
)
def test_cms_entity_types_registered(app, entity_type, manage_permission):
    assert is_registered(entity_type)
    registration = get_entity_type(entity_type)
    assert registration is not None
    assert registration.manage_permission == manage_permission


def _make_post(db, post_type):
    from plugins.cms.src.models.cms_post import CmsPost
    from uuid import uuid4

    post = CmsPost()
    post.type = post_type
    post.slug = f"{post_type}-tagged-{uuid4().hex[:8]}"
    post.title = "Tagged content"
    post.content_json = {}
    post.status = "published"
    db.session.add(post)
    db.session.commit()
    return post


def test_post_detail_appends_empty_tags_and_custom_fields(app, db, client):
    post = _make_post(db, "post")

    body = client.get(f"/api/v1/cms/posts/{post.slug}?type=post").get_json()

    assert body["tags"] == []
    assert body["custom_fields"] == {}
    # The existing taxonomy stays present (categories + legacy tag terms).
    assert "terms" in body


def test_page_detail_appends_tags_keyed_by_cms_page(app, db, client):
    page = _make_post(db, "page")

    with app.app_context():
        app.container.tags_and_custom_fields().set_tags("cms_page", page.id, ["howto"])

    body = client.get(f"/api/v1/cms/posts/{page.slug}?type=page").get_json()

    assert body["tags"] == ["howto"]


def test_post_detail_tags_keyed_by_cms_post(app, db, client):
    post = _make_post(db, "post")

    with app.app_context():
        app.container.tags_and_custom_fields().set_tags("cms_post", post.id, ["news"])

    body = client.get(f"/api/v1/cms/posts/{post.slug}?type=post").get_json()

    assert body["tags"] == ["news"]
