"""SearchRepository — Postgres full-text search over cms_post (S47.4).

Queries the generated ``search_vector`` GIN-indexed column with
``websearch_to_tsquery`` and ranks by ``ts_rank``. Returns the same paginated
shape PostRepository emits, so SearchService and PostService serialize results
identically (DRY). Callers pass a non-blank query; the blank-query short-circuit
lives in SearchService.
"""
from typing import Any, Dict, List, Optional

from sqlalchemy import func

from vbwd.models.entity_tag import EntityTag

from plugins.cms.src.models.cms_post import CmsPost
from plugins.cms.src.models.cms_term import CmsTerm, CATEGORY_TERM_TYPE, TAG_TERM_TYPE
from plugins.cms.src.models.cms_post_term import CmsPostTerm
from plugins.cms.src.repositories.post_repository import POST_TAG_ENTITY_TYPE


# Text search configuration for ``websearch_to_tsquery`` / ``to_tsvector``.
# Must match the language used by the generated column (cms_post.search_vector).
SEARCH_CONFIG = "english"


class SearchRepository:
    """Full-text search data access for cms_post."""

    def __init__(self, session) -> None:
        self.session = session

    def search(
        self,
        *,
        query: str,
        status: Optional[str] = None,
        post_type: Optional[str] = None,
        term_type: Optional[str] = None,
        term_slug: Optional[str] = None,
        page: int = 1,
        per_page: int = 20,
    ) -> Dict[str, Any]:
        ts_query = func.websearch_to_tsquery(SEARCH_CONFIG, query)
        base = self.session.query(CmsPost).filter(
            CmsPost.search_vector.op("@@")(ts_query)
        )
        if status:
            base = base.filter(CmsPost.status == status)
        if post_type:
            base = base.filter(CmsPost.type == post_type)
        if term_type and term_slug:
            if term_type == TAG_TERM_TYPE:
                # D7: tags live in the core vbwd_entity_tag table, not in
                # cms_term('tag')/cms_post_term. Mirror PostRepository.
                # find_by_tag_slug — the bounded D5-allowed small-N reverse-index
                # lookup over the CMS post set (NOT the 1M-SKU catalog path).
                base = base.join(
                    EntityTag,
                    (EntityTag.entity_id == CmsPost.id)
                    & (EntityTag.entity_type == POST_TAG_ENTITY_TYPE),
                ).filter(EntityTag.tag_slug == term_slug)
            else:
                base = (
                    base.join(CmsPostTerm, CmsPostTerm.post_id == CmsPost.id)
                    .join(CmsTerm, CmsTerm.id == CmsPostTerm.term_id)
                    .filter(CmsTerm.term_type == term_type, CmsTerm.slug == term_slug)
                )

        total = base.count()
        rank = func.ts_rank(CmsPost.search_vector, ts_query)
        items = (
            base.order_by(rank.desc(), CmsPost.updated_at.desc())
            .offset((page - 1) * per_page)
            .limit(per_page)
            .all()
        )
        return {
            "items": items,
            "total": total,
            "page": page,
            "per_page": per_page,
            "pages": max(1, (total + per_page - 1) // per_page),
        }

    def primary_categories_for_posts(
        self, post_ids: List[Any]
    ) -> Dict[Any, Dict[str, str]]:
        """Map each post id → its first ``category`` term ``{slug, name}``.

        One grouped query over the cms_post_term → cms_term junction for the
        whole (page-capped) result set — never a per-item lookup (no N+1). The
        "first" category is deterministic: lowest term ``sort_order``, then the
        earliest junction ``created_at``. Posts with no category term are simply
        absent from the map (the caller treats a miss as ``None``).
        """
        if not post_ids:
            return {}
        rows = (
            self.session.query(
                CmsPostTerm.post_id,
                CmsTerm.slug,
                CmsTerm.name,
            )
            .join(CmsTerm, CmsTerm.id == CmsPostTerm.term_id)
            .filter(
                CmsPostTerm.post_id.in_(post_ids),
                CmsTerm.term_type == CATEGORY_TERM_TYPE,
            )
            .order_by(
                CmsPostTerm.post_id,
                CmsTerm.sort_order.asc(),
                CmsPostTerm.created_at.asc(),
            )
            .all()
        )
        primary_by_post: Dict[Any, Dict[str, str]] = {}
        for post_id, slug, name in rows:
            if post_id not in primary_by_post:
                primary_by_post[post_id] = {"slug": slug, "name": name}
        return primary_by_post
