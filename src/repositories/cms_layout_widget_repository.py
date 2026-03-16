"""CmsLayoutWidget repository."""
from typing import List, Dict, Any
from uuid import uuid4
from plugins.cms.src.models.cms_layout_widget import CmsLayoutWidget


class CmsLayoutWidgetRepository:
    def __init__(self, session) -> None:
        self.session = session

    def find_by_layout(self, layout_id: str) -> List[CmsLayoutWidget]:
        return (
            self.session.query(CmsLayoutWidget)
            .filter(CmsLayoutWidget.layout_id == layout_id)
            .order_by(CmsLayoutWidget.sort_order.asc())
            .all()
        )

    def find_by_widget(self, widget_id: str) -> List[CmsLayoutWidget]:
        return (
            self.session.query(CmsLayoutWidget)
            .filter(CmsLayoutWidget.widget_id == widget_id)
            .all()
        )

    def replace_for_layout(
        self, layout_id: str, assignments: List[Dict[str, Any]]
    ) -> List[CmsLayoutWidget]:
        """Replace all widget assignments for a layout atomically."""
        self.session.query(CmsLayoutWidget).filter(
            CmsLayoutWidget.layout_id == layout_id
        ).delete(synchronize_session="fetch")
        created = []
        for a in assignments:
            lw = CmsLayoutWidget()
            lw.id = uuid4()
            lw.layout_id = layout_id
            lw.widget_id = a["widget_id"]
            lw.area_name = a["area_name"]
            lw.sort_order = a.get("sort_order", 0)
            self.session.add(lw)
            created.append(lw)
        self.session.flush()
        self.session.commit()
        return created

    def delete_by_layout(self, layout_id: str) -> None:
        self.session.query(CmsLayoutWidget).filter(
            CmsLayoutWidget.layout_id == layout_id
        ).delete(synchronize_session="fetch")
        self.session.flush()
        self.session.commit()
