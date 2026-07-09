"""PostTermRepository — data access for the cms_post_term junction (S47.0)."""
from typing import List, Optional

from plugins.cms.src.models.cms_post_term import CmsPostTerm


class PostTermRepository:
    """Repository for the post↔term junction table."""

    def __init__(self, session) -> None:
        self.session = session

    def find_by_post(self, post_id: str) -> List[CmsPostTerm]:
        return (
            self.session.query(CmsPostTerm).filter(CmsPostTerm.post_id == post_id).all()
        )

    def replace_for_post(
        self,
        post_id: str,
        term_ids: List[str],
        pinned_term_ids: Optional[List[str]] = None,
    ) -> List[CmsPostTerm]:
        """Replace all term links for a post with the given set.

        ``pinned_term_ids`` marks which of ``term_ids`` are pinned (sticky) in
        their term's archive (writes ``cms_post_term.pinned``):

        * An explicit list (even empty) is AUTHORITATIVE — every term not in it
          is written unpinned. This is the editor's save path.
        * ``None`` (a legacy caller that predates pins — e.g. the bulk term
          ops) PRESERVES each surviving term's current pin state, so those
          callers never silently drop an admin's pins.
        """
        existing_pins = {
            str(link.term_id): bool(link.pinned) for link in self.find_by_post(post_id)
        }
        if pinned_term_ids is None:

            def _is_pinned(term_id: str) -> bool:
                return existing_pins.get(str(term_id), False)

        else:
            pinned = {str(term_id) for term_id in pinned_term_ids}

            def _is_pinned(term_id: str) -> bool:
                return str(term_id) in pinned

        self.session.query(CmsPostTerm).filter(CmsPostTerm.post_id == post_id).delete(
            synchronize_session="fetch"
        )

        created: List[CmsPostTerm] = []
        for term_id in term_ids:
            link = CmsPostTerm()
            link.post_id = post_id
            link.term_id = term_id
            link.pinned = _is_pinned(term_id)
            self.session.add(link)
            created.append(link)

        self.session.flush()
        self.session.commit()
        return created
