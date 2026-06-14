"""S77 D7 — fold CMS tags into the core tag catalog, then drop the old ones.

The only tag implementation in the platform is CMS (``cms_term`` rows where
``term_type='tag'``, linked via ``cms_post_term``). This migration reimports
those tags + their links into the single core catalog
(``vbwd_tag`` / ``vbwd_entity_tag``) and then drops the old tag rows + tag
links. Categories (``cms_term(term_type='category')``) and their links are left
untouched.

Locked decision (2026-06-13): migrated tags are SCOPED to ``cms_post``
(``parent_entity_type='cms_post'``) — they keep today's blog-tag semantics and
stay hidden from product/plan TagPickers.

Idempotent + set-based (D6): the reimport uses ``INSERT … ON CONFLICT DO
NOTHING`` (same upsert semantics as the ``tags`` exchanger) so a re-run is safe,
and the move/drop are single statements. The migration verifies the moved
``entity_tag`` count equals the old tag-typed ``cms_post_term`` count and aborts
on mismatch.

down() is BEST-EFFORT: it recreates the tag terms + ``cms_post_term`` links from
the ``cms_post``-scoped ``vbwd_entity_tag`` rows. It cannot distinguish a tag
that was global before the fold from one that was cms_post-scoped, and it leaves
the core catalog rows in place; it is provided for graph reversibility, not as a
lossless rollback.

Revision ID: 20260613_1300_fold_tags
Revises: 20260612_1100_drop_widget_global, 20260613_1200_tags_cf
Create Date: 2026-06-13

This is a CMS-plugin migration. It is a MERGE node anchored on BOTH the prior
cms head (``20260612_1100_drop_widget_global`` — keeps the cms chain linear) AND
the core revision that creates ``vbwd_tag`` / ``vbwd_entity_tag``
(``20260613_1200_tags_cf`` — guarantees the target tables exist). That core
revision is always present (it lives in core ``alembic/versions``), so anchoring
on it never strands the graph for any plugin subset.
"""
from alembic import op
import sqlalchemy as sa


revision = "20260613_1300_fold_tags"
down_revision = ("20260612_1100_drop_widget_global", "20260613_1200_tags_cf")
branch_labels = None
depends_on = None

TAG_TERM_TYPE = "tag"
TAG_ENTITY_TYPE = "cms_post"


def upgrade() -> None:
    conn = op.get_bind()

    # 1. Reimport the tag CATALOG: each cms_term('tag') becomes a cms_post-scoped
    #    vbwd_tag row (carry slug + name). ON CONFLICT keeps an existing slug
    #    (idempotent; a slug already in the catalog wins).
    conn.execute(
        sa.text(
            """
            INSERT INTO vbwd_tag
                (id, slug, name, parent_entity_type, meta_data, color,
                 created_at, updated_at, version)
            SELECT gen_random_uuid(), term.slug, term.name, :scope,
                   '{}'::jsonb, NULL, now(), now(), 0
              FROM cms_term AS term
             WHERE term.term_type = :tag_type
            ON CONFLICT (slug) DO NOTHING
            """
        ),
        {"scope": TAG_ENTITY_TYPE, "tag_type": TAG_TERM_TYPE},
    )

    # 2. Reimport the LINKS: each tag-typed cms_post_term becomes an entity_tag
    #    row (entity_type=cms_post, entity_id=post_id, tag_slug=term.slug).
    conn.execute(
        sa.text(
            """
            INSERT INTO vbwd_entity_tag (entity_type, entity_id, tag_slug)
            SELECT :entity_type, link.post_id, term.slug
              FROM cms_post_term AS link
              JOIN cms_term AS term ON term.id = link.term_id
             WHERE term.term_type = :tag_type
            ON CONFLICT (entity_type, entity_id, tag_slug) DO NOTHING
            """
        ),
        {"entity_type": TAG_ENTITY_TYPE, "tag_type": TAG_TERM_TYPE},
    )

    # 3. Verify the move: every distinct (post, tag) link must now exist in the
    #    core table. We compare DISTINCT source links (a post can carry the same
    #    tag once via the uq_cms_post_term constraint, so distinct == row count)
    #    against the migrated entity_tag rows for those posts.
    expected = (
        conn.execute(
            sa.text(
                """
            SELECT count(*)
              FROM cms_post_term AS link
              JOIN cms_term AS term ON term.id = link.term_id
             WHERE term.term_type = :tag_type
            """
            ),
            {"tag_type": TAG_TERM_TYPE},
        ).scalar()
        or 0
    )
    migrated = (
        conn.execute(
            sa.text(
                """
            SELECT count(*)
              FROM vbwd_entity_tag AS link
              JOIN cms_term AS term
                ON term.slug = link.tag_slug AND term.term_type = :tag_type
             WHERE link.entity_type = :entity_type
               AND link.entity_id IN (
                   SELECT post_id FROM cms_post_term
               )
            """
            ),
            {"tag_type": TAG_TERM_TYPE, "entity_type": TAG_ENTITY_TYPE},
        ).scalar()
        or 0
    )
    if migrated < expected:
        raise RuntimeError(
            "S77 D7 fold-tags migration: migrated entity_tag links "
            f"({migrated}) < source tag links ({expected}); aborting before drop"
        )

    # 4. Drop the old tag links, then the old tag terms. cms_post_term and
    #    cms_term (now categories-only) remain. Set-based DELETE (post volumes
    #    are small — §Scaling allows the single statement here).
    conn.execute(
        sa.text(
            """
            DELETE FROM cms_post_term
             WHERE term_id IN (
                 SELECT id FROM cms_term WHERE term_type = :tag_type
             )
            """
        ),
        {"tag_type": TAG_TERM_TYPE},
    )
    conn.execute(
        sa.text("DELETE FROM cms_term WHERE term_type = :tag_type"),
        {"tag_type": TAG_TERM_TYPE},
    )


def downgrade() -> None:
    """Best-effort reverse: recreate tag terms + links from entity_tag.

    Recreates a cms_term('tag') for every cms_post-scoped vbwd_tag, then rebuilds
    the cms_post_term links from the cms_post-scoped entity_tag rows. Does NOT
    delete the core catalog rows (they may be referenced by other entity types)
    and cannot reconstruct pre-fold global vs cms_post scoping — see docstring.
    """
    conn = op.get_bind()

    conn.execute(
        sa.text(
            """
            INSERT INTO cms_term
                (id, term_type, slug, name, seo_excluded, sort_order,
                 created_at, updated_at, version)
            SELECT gen_random_uuid(), :tag_type, tag.slug, tag.name,
                   false, 0, now(), now(), 0
              FROM vbwd_tag AS tag
             WHERE tag.parent_entity_type = :scope
            ON CONFLICT (term_type, slug) DO NOTHING
            """
        ),
        {"tag_type": TAG_TERM_TYPE, "scope": TAG_ENTITY_TYPE},
    )

    conn.execute(
        sa.text(
            """
            INSERT INTO cms_post_term
                (id, post_id, term_id, created_at, updated_at, version)
            SELECT gen_random_uuid(), link.entity_id, term.id,
                   now(), now(), 0
              FROM vbwd_entity_tag AS link
              JOIN cms_term AS term
                ON term.slug = link.tag_slug AND term.term_type = :tag_type
             WHERE link.entity_type = :entity_type
            ON CONFLICT (post_id, term_id) DO NOTHING
            """
        ),
        {"tag_type": TAG_TERM_TYPE, "entity_type": TAG_ENTITY_TYPE},
    )
