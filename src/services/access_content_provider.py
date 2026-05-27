"""CMS implementation of ``IAccessLevelContentProvider``.

Returns CMS pages and layout-widget assignments whose
``required_access_level_ids`` JSON column contains the given access level
id. The shape of each item is preserved to match what the admin route
emitted before S01 (FE backward-compat).
"""
from typing import Any, Mapping

from vbwd.extensions import db
from vbwd.services.access_level_content_provider import (
    IAccessLevelContentProvider,
)

from plugins.cms.src.models.cms_layout_widget import CmsLayoutWidget
from plugins.cms.src.models.cms_page import CmsPage


class CmsAccessContentProvider(IAccessLevelContentProvider):
    """Reports CMS pages + widget assignments restricted to a user level."""

    def list_restricted_content_for_level(
        self, level_id: str
    ) -> Mapping[str, list[Mapping[str, Any]]]:
        pages: list[Mapping[str, Any]] = []
        for page in db.session.query(CmsPage).all():
            required_ids = page.required_access_level_ids or []
            if level_id in required_ids:
                pages.append(
                    {
                        "id": str(page.id),
                        "name": page.name,
                        "slug": page.slug,
                    }
                )

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
