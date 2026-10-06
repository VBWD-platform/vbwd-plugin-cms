"""The public cms serialization boundary (S152 W4).

``CmsPost.to_dict()`` is shared by admin and public reads. Some of its fields
are admin-only — ``preview_token`` lets anyone holding it preview the post in
any status, so it must never reach an anonymous reader. Every public cms route
passes its JSON payload through ``public_payload`` (one home, DRY); admin
routes keep the full dict for fe-admin's preview links.
"""
from typing import Any

ADMIN_ONLY_POST_FIELDS = frozenset({"preview_token"})


def public_payload(payload: Any) -> Any:
    """Return a copy of ``payload`` with admin-only fields removed at any depth."""
    if isinstance(payload, dict):
        return {
            key: public_payload(value)
            for key, value in payload.items()
            if key not in ADMIN_ONLY_POST_FIELDS
        }
    if isinstance(payload, list):
        return [public_payload(item) for item in payload]
    return payload
