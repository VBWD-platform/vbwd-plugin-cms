"""CmsPageWidget repository."""
from typing import List, Dict, Any
from plugins.cms.src.models.cms_page_widget import CmsPageWidget


class CmsPageWidgetRepository:
    def __init__(self, session) -> None:
        self.session = session

    def find_by_page(self, page_id: str) -> List[CmsPageWidget]:
        return (
            self.session.query(CmsPageWidget)
            .filter(CmsPageWidget.page_id == page_id)
            .order_by(CmsPageWidget.sort_order.asc())
            .all()
        )

    def replace_for_page(
        self, page_id: str, assignments: List[Dict[str, Any]]
    ) -> List[CmsPageWidget]:
        """Replace all page widget assignments atomically."""
        self.session.query(CmsPageWidget).filter(
            CmsPageWidget.page_id == page_id
        ).delete(synchronize_session="fetch")
        created = []
        for assignment in assignments:
            page_widget = CmsPageWidget()
            page_widget.page_id = page_id
            page_widget.widget_id = assignment["widget_id"]
            page_widget.area_name = assignment["area_name"]
            page_widget.sort_order = assignment.get("sort_order", 0)
            page_widget.required_access_level_ids = assignment.get(
                "required_access_level_ids", []
            )
            self.session.add(page_widget)
            created.append(page_widget)
        self.session.flush()
        self.session.commit()
        return created

    def delete_by_page(self, page_id: str) -> None:
        self.session.query(CmsPageWidget).filter(
            CmsPageWidget.page_id == page_id
        ).delete(synchronize_session="fetch")
        self.session.flush()
        self.session.commit()
