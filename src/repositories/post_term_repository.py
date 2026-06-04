"""PostTermRepository — data access for the cms_post_term junction (S47.0)."""
from typing import List

from plugins.cms.src.models.cms_post_term import CmsPostTerm


class PostTermRepository:
    """Repository for the post↔term junction table."""

    def __init__(self, session) -> None:
        self.session = session

    def find_by_post(self, post_id: str) -> List[CmsPostTerm]:
        return (
            self.session.query(CmsPostTerm).filter(CmsPostTerm.post_id == post_id).all()
        )

    def replace_for_post(self, post_id: str, term_ids: List[str]) -> List[CmsPostTerm]:
        """Replace all term links for a post with the given set."""
        self.session.query(CmsPostTerm).filter(CmsPostTerm.post_id == post_id).delete(
            synchronize_session="fetch"
        )

        created: List[CmsPostTerm] = []
        for term_id in term_ids:
            link = CmsPostTerm()
            link.post_id = post_id
            link.term_id = term_id
            self.session.add(link)
            created.append(link)

        self.session.flush()
        self.session.commit()
        return created
