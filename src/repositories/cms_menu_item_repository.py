"""CmsMenuItem repository."""
from typing import List, Dict, Any
from uuid import uuid4
from plugins.cms.src.models.cms_menu_item import CmsMenuItem


class CmsMenuItemRepository:
    def __init__(self, session) -> None:
        self.session = session

    def find_tree_by_widget(self, widget_id: str) -> List[CmsMenuItem]:
        return (
            self.session.query(CmsMenuItem)
            .filter(CmsMenuItem.widget_id == widget_id)
            .order_by(CmsMenuItem.sort_order.asc())
            .all()
        )

    def replace_tree(self, widget_id: str, items: List[Dict[str, Any]]) -> List[CmsMenuItem]:
        """Delete all existing items for widget and insert new tree atomically.

        Remaps parent_id values from import-time placeholder IDs to the real
        UUIDs assigned during this insert, so multilevel menus from JSON import
        don't violate the self-referential FK constraint.
        """
        self.session.query(CmsMenuItem).filter(CmsMenuItem.widget_id == widget_id).delete(
            synchronize_session="fetch"
        )
        # Pass 1: assign new UUIDs and build old_id → new_id mapping
        id_map: Dict[str, Any] = {}
        created = []
        for item_data in items:
            new_id = uuid4()
            old_id = item_data.get("id")
            if old_id:
                id_map[str(old_id)] = new_id
            item = CmsMenuItem()
            item.id = new_id
            item.widget_id = widget_id
            item.parent_id = None  # will be set in pass 2
            item.label = item_data.get("label", "")
            item.url = item_data.get("url")
            item.page_slug = item_data.get("page_slug")
            item.target = item_data.get("target", "_self")
            item.icon = item_data.get("icon")
            item.sort_order = item_data.get("sort_order", 0)
            created.append((item, item_data.get("parent_id")))
            self.session.add(item)

        # Pass 2: resolve parent_id references using the mapping
        for item, old_parent_id in created:
            if old_parent_id is not None:
                item.parent_id = id_map.get(str(old_parent_id), old_parent_id)

        self.session.flush()
        self.session.commit()
        return [item for item, _ in created]

    def delete_by_widget(self, widget_id: str) -> None:
        self.session.query(CmsMenuItem).filter(CmsMenuItem.widget_id == widget_id).delete(
            synchronize_session="fetch"
        )
        self.session.flush()
        self.session.commit()
