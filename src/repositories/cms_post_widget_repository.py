"""CmsPostWidget repository — per-post widget assignment data access (S55)."""
from typing import List, Dict, Any
from plugins.cms.src.models.cms_post_widget import CmsPostWidget


class CmsPostWidgetRepository:
    def __init__(self, session) -> None:
        self.session = session

    def find_by_post(self, post_id: str) -> List[CmsPostWidget]:
        return (
            self.session.query(CmsPostWidget)
            .filter(CmsPostWidget.post_id == post_id)
            .order_by(CmsPostWidget.sort_order.asc())
            .all()
        )

    def replace_for_post(
        self, post_id: str, assignments: List[Dict[str, Any]]
    ) -> List[CmsPostWidget]:
        """Replace all post widget assignments atomically."""
        self.session.query(CmsPostWidget).filter(
            CmsPostWidget.post_id == post_id
        ).delete(synchronize_session="fetch")
        created = []
        for assignment in assignments:
            post_widget = CmsPostWidget()
            post_widget.post_id = post_id
            post_widget.widget_id = assignment["widget_id"]
            post_widget.area_name = assignment["area_name"]
            post_widget.sort_order = assignment.get("sort_order", 0)
            post_widget.required_access_level_ids = assignment.get(
                "required_access_level_ids", []
            )
            post_widget.config_override = assignment.get("config_override")
            self.session.add(post_widget)
            created.append(post_widget)
        self.session.flush()
        self.session.commit()
        return created

    def delete_by_post(self, post_id: str) -> None:
        self.session.query(CmsPostWidget).filter(
            CmsPostWidget.post_id == post_id
        ).delete(synchronize_session="fetch")
        self.session.flush()
        self.session.commit()
