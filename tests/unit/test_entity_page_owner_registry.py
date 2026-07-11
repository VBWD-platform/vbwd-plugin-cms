"""Unit: the content-owner-type registry — the OCP seam for entity pages (S128).

Mirrors ``post_type_registry`` exactly: a module-level dict is the single source
of truth; other plugins register an opaque owner type (``dataset`` /
``shop_product`` / …) with an ``authorize`` callback, and CMS looks it up with
zero vertical knowledge.

Engineering requirements (binding, restated): TDD-first; DevOps-first; SOLID
(OCP — a new owner type is a registration, never a cms edit); DI; DRY; Liskov
(an unregistered key resolves to None — the caller decides 404, never a crash);
clean code; no overengineering. Quality guard:
``bin/pre-commit-check.sh --plugin cms --full``.
"""
import pytest

from plugins.cms.src.services.entity_page_owner_registry import (
    ContentOwnerType,
    register_content_owner_type,
    get_content_owner_type,
    is_registered,
    list_content_owner_types,
    clear_content_owner_types,
)


@pytest.fixture(autouse=True)
def _clean_registry():
    clear_content_owner_types()
    yield
    clear_content_owner_types()


def test_register_and_get_round_trips():
    owner_type = ContentOwnerType(
        key="dataset", label="Dataset", authorize=lambda user, owner_id: True
    )
    register_content_owner_type(owner_type)

    assert is_registered("dataset") is True
    assert get_content_owner_type("dataset") is owner_type
    assert get_content_owner_type("dataset").label == "Dataset"


def test_unknown_key_resolves_to_none_not_error():
    assert is_registered("nope") is False
    assert get_content_owner_type("nope") is None


def test_authorize_callback_is_carried_and_invoked():
    seen = {}

    def _authorize(user, owner_id):
        seen["user"] = user
        seen["owner_id"] = owner_id
        return owner_id == "allowed"

    register_content_owner_type(
        ContentOwnerType(key="dataset", label="Dataset", authorize=_authorize)
    )
    resolved = get_content_owner_type("dataset")

    assert resolved.authorize("the-user", "allowed") is True
    assert resolved.authorize("the-user", "other") is False
    assert seen == {"user": "the-user", "owner_id": "other"}


def test_register_replaces_by_key():
    first = ContentOwnerType("dataset", "One", authorize=lambda u, o: True)
    second = ContentOwnerType("dataset", "Two", authorize=lambda u, o: False)
    register_content_owner_type(first)
    register_content_owner_type(second)

    assert get_content_owner_type("dataset") is second
    assert len(list_content_owner_types()) == 1


def test_list_and_clear():
    register_content_owner_type(
        ContentOwnerType("dataset", "Dataset", authorize=lambda u, o: True)
    )
    register_content_owner_type(
        ContentOwnerType("shop_product", "Product", authorize=lambda u, o: True)
    )
    assert {owner.key for owner in list_content_owner_types()} == {
        "dataset",
        "shop_product",
    }

    clear_content_owner_types()
    assert list_content_owner_types() == []


def test_owner_type_is_frozen():
    owner_type = ContentOwnerType("dataset", "Dataset", authorize=lambda u, o: True)
    with pytest.raises(Exception):
        owner_type.key = "mutated"  # type: ignore[misc]
