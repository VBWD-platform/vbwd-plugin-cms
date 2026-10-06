"""Unit: the ONE public-serialization boundary strips admin-only post fields (S152 W4).

``CmsPost.to_dict()`` keeps ``preview_token`` for fe-admin preview links; the
public cms routes pass every payload through ``public_payload`` so the token
never leaves on an anonymous read — top-level, inside ``items``, or nested.

Engineering requirements (binding, restated): TDD-first; DevOps-first; SOLID/
DI/DRY (one helper for every public route); Liskov (same shape minus the
secret, input never mutated); clean code; no overengineering. Quality guard:
``bin/pre-commit-check.sh --plugin cms --full``.
"""
from plugins.cms.src.services.public_payload import public_payload


def test_strips_top_level_preview_token():
    assert public_payload({"id": "a", "preview_token": "secret"}) == {"id": "a"}


def test_strips_preview_token_from_list_items_and_nested_dicts():
    payload = {
        "items": [{"id": "a", "preview_token": "one"}, {"id": "b"}],
        "total": 2,
        "nested": {"post": {"preview_token": "two", "slug": "x"}},
    }

    assert public_payload(payload) == {
        "items": [{"id": "a"}, {"id": "b"}],
        "total": 2,
        "nested": {"post": {"slug": "x"}},
    }


def test_does_not_mutate_the_input():
    original = {"items": [{"id": "a", "preview_token": "one"}]}

    public_payload(original)

    assert original["items"][0]["preview_token"] == "one"


def test_scalars_and_lists_pass_through():
    assert public_payload([1, "two", None]) == [1, "two", None]
    assert public_payload("text") == "text"
