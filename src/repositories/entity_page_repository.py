"""EntityPageRepository — data access for the cms_entity_page link (S128).

A narrow port over the attachment table: look a link up by owner+slot, list an
owner's links (all slots, for delete), upsert a link, and drop an owner's
link(s). The service depends on this abstraction, never on the model — same
pattern as the other cms repositories.
"""
from typing import List, Optional

from plugins.cms.src.models.cms_entity_page import CmsEntityPage


class EntityPageRepository:
    """Repository for CmsEntityPage database operations."""

    def __init__(self, session) -> None:
        self.session = session

    def get_by_owner(
        self, owner_type: str, owner_id: str, slot: str = "main"
    ) -> Optional[CmsEntityPage]:
        return (
            self.session.query(CmsEntityPage)
            .filter(
                CmsEntityPage.owner_type == owner_type,
                CmsEntityPage.owner_id == str(owner_id),
                CmsEntityPage.slot == slot,
            )
            .first()
        )

    def find_by_owner(self, owner_type: str, owner_id: str) -> List[CmsEntityPage]:
        """Every slot's link for one owner (used by delete_for_owner)."""
        return (
            self.session.query(CmsEntityPage)
            .filter(
                CmsEntityPage.owner_type == owner_type,
                CmsEntityPage.owner_id == str(owner_id),
            )
            .all()
        )

    def upsert(
        self, owner_type: str, owner_id: str, slot: str, post_id: str
    ) -> CmsEntityPage:
        """Create or re-point the (owner_type, owner_id, slot) link."""
        link = self.get_by_owner(owner_type, owner_id, slot)
        if link is None:
            link = CmsEntityPage()
            link.owner_type = owner_type
            link.owner_id = str(owner_id)
            link.slot = slot
            self.session.add(link)
        link.post_id = post_id
        self.session.flush()
        self.session.commit()
        return link

    def delete_by_owner(self, owner_type: str, owner_id: str) -> int:
        """Delete every slot's link for one owner. Returns the count removed."""
        links = self.find_by_owner(owner_type, owner_id)
        for link in links:
            self.session.delete(link)
        self.session.flush()
        self.session.commit()
        return len(links)
