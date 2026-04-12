"""CmsLayoutWidget repository."""
from typing import List, Dict, Any
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
            layout_widget = CmsLayoutWidget()
            layout_widget.layout_id = layout_id
            layout_widget.widget_id = a["widget_id"]
            layout_widget.area_name = a["area_name"]
            layout_widget.sort_order = a.get("sort_order", 0)
            layout_widget.required_access_level_ids = a.get(
                "required_access_level_ids", []
            )
            self.session.add(layout_widget)
            created.append(layout_widget)
        self.session.flush()
        self.session.commit()
        return created

    def delete_by_layout(self, layout_id: str) -> None:
        self.session.query(CmsLayoutWidget).filter(
            CmsLayoutWidget.layout_id == layout_id
        ).delete(synchronize_session="fetch")
        self.session.flush()
        self.session.commit()
