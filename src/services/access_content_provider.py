"""CMS implementation of ``IAccessLevelContentProvider``.

Returns CMS layout-widget assignments whose ``required_access_level_ids`` JSON
column contains the given access level id. The shape of each item is preserved
to match what the admin route emitted before S01 (FE backward-compat).

The legacy ``cms_page`` access-restriction surface is retired (S105): the unified
``cms_post`` table carries no page-level ``required_access_level_ids`` column, so
``pages`` is now always empty (the key is kept for FE backward-compat). Widget
assignments — the only remaining access-restricted CMS surface — are unchanged.
"""
from typing import Any, Mapping

from vbwd.extensions import db
from vbwd.services.access_level_content_provider import (
    IAccessLevelContentProvider,
)

from plugins.cms.src.models.cms_layout_widget import CmsLayoutWidget


class CmsAccessContentProvider(IAccessLevelContentProvider):
    """Reports CMS widget assignments restricted to a user level."""

    def list_restricted_content_for_level(
        self, level_id: str
    ) -> Mapping[str, list[Mapping[str, Any]]]:
        # Pages no longer carry an access-restriction column (S105); the key is
        # preserved (always empty) so the admin FE contract stays stable.
        pages: list[Mapping[str, Any]] = []

        widgets: list[Mapping[str, Any]] = []
        for assignment in db.session.query(CmsLayoutWidget).all():
            required_ids = assignment.required_access_level_ids or []
            if level_id in required_ids:
                widgets.append(
                    {
                        "id": str(assignment.id),
                        "area_name": assignment.area_name,
                        "widget_id": str(assignment.widget_id),
                        "layout_id": str(assignment.layout_id),
                    }
                )

        return {"pages": pages, "widgets": widgets}
