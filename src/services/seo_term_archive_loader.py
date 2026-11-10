"""DB-paged term-archive sources for the sitemap (S154 P2).

A term archive is listed only when it has at least one PUBLISHED post — the
same validity rule the public term resolution applies to tags (and an empty
category archive is thin content). Each source runs ONE grouped query per call:
``count_archives`` counts the groups, ``archive_page`` reads one
``ORDER BY <key> LIMIT/OFFSET`` window with the newest post's ``updated_at`` as
``lastmod`` (an aggregate in the same query — no per-term lookup).

* categories live in ``cms_term`` (``term_type == "category"``) and honour the
  term's own ``seo_excluded`` flag;
* tags live in the core ``vbwd_entity_tag`` index (no ``cms_term`` rows), joined
  on the cms post entity type exactly like the tag archive listing.
"""
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional, Sequence

from sqlalchemy import func

from vbwd.models.entity_tag import EntityTag

from plugins.cms.src.models.cms_post import CmsPost, POST_STATUS_PUBLISHED
from plugins.cms.src.models.cms_post_term import CmsPostTerm
from plugins.cms.src.models.cms_term import CATEGORY_TERM_TYPE, CmsTerm
from plugins.cms.src.repositories.post_repository import POST_TAG_ENTITY_TYPE


@dataclass(frozen=True)
class TermArchiveRow:
    """One term archive: its slug and the newest change to its listing."""

    slug: str
    lastmod: Optional[datetime]


def _newest(*moments: Optional[datetime]) -> Optional[datetime]:
    present = [moment for moment in moments if moment is not None]
    return max(present) if present else None


class CategoryArchiveSource:
    """Category archives with ≥1 published post, in ``cms_term.id`` order."""

    def __init__(self, session) -> None:
        self._session = session

    def _grouped_query(self, excluded_slugs: Sequence[str]):
        query = (
            self._session.query(
                CmsTerm.id,
                CmsTerm.slug,
                CmsTerm.updated_at,
                func.max(CmsPost.updated_at),
            )
            .join(CmsPostTerm, CmsPostTerm.term_id == CmsTerm.id)
            .join(CmsPost, CmsPost.id == CmsPostTerm.post_id)
            .filter(
                CmsTerm.term_type == CATEGORY_TERM_TYPE,
                CmsTerm.seo_excluded.is_(False),
                CmsPost.status == POST_STATUS_PUBLISHED,
            )
            .group_by(CmsTerm.id, CmsTerm.slug, CmsTerm.updated_at)
        )
        if excluded_slugs:
            query = query.filter(CmsTerm.slug.notin_(list(excluded_slugs)))
        return query

    def count_archives(self, excluded_slugs: Sequence[str] = ()) -> int:
        return self._grouped_query(excluded_slugs).count()

    def archive_page(
        self, offset: int, limit: int, excluded_slugs: Sequence[str] = ()
    ) -> List[TermArchiveRow]:
        records = (
            self._grouped_query(excluded_slugs)
            .order_by(CmsTerm.id)
            .offset(offset)
            .limit(limit)
            .all()
        )
        return [
            TermArchiveRow(slug=slug, lastmod=_newest(term_updated_at, post_updated_at))
            for _term_id, slug, term_updated_at, post_updated_at in records
        ]


class TagArchiveSource:
    """Tag archives (core tag index) with ≥1 published post, in slug order."""

    def __init__(self, session) -> None:
        self._session = session

    def _grouped_query(self, excluded_slugs: Sequence[str]):
        query = (
            self._session.query(EntityTag.tag_slug, func.max(CmsPost.updated_at))
            .join(
                CmsPost,
                (EntityTag.entity_id == CmsPost.id)
                & (EntityTag.entity_type == POST_TAG_ENTITY_TYPE),
            )
            .filter(CmsPost.status == POST_STATUS_PUBLISHED)
            .group_by(EntityTag.tag_slug)
        )
        if excluded_slugs:
            query = query.filter(EntityTag.tag_slug.notin_(list(excluded_slugs)))
        return query

    def count_archives(self, excluded_slugs: Sequence[str] = ()) -> int:
        return self._grouped_query(excluded_slugs).count()

    def archive_page(
        self, offset: int, limit: int, excluded_slugs: Sequence[str] = ()
    ) -> List[TermArchiveRow]:
        records = (
            self._grouped_query(excluded_slugs)
            .order_by(EntityTag.tag_slug)
            .offset(offset)
            .limit(limit)
            .all()
        )
        return [
            TermArchiveRow(slug=tag_slug, lastmod=post_updated_at)
            for tag_slug, post_updated_at in records
        ]
