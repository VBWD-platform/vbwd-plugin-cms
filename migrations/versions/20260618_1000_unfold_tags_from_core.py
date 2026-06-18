"""S77 reversal — unfold CMS tags from the core catalog back into the taxonomy.

Reverses the data move done by ``20260613_1300_fold_tags``: CMS tags belong to
the CMS taxonomy system (``cms_term`` rows with ``term_type='tag'``, linked via
``cms_post_term``), NOT the generic core ``vbwd_tag`` catalog. This migration:

1. For each ``cms_post``-scoped ``vbwd_tag`` (``parent_entity_type='cms_post'``),
   find-or-create a ``cms_term(term_type='tag')`` with the same slug + name.
2. For each ``vbwd_entity_tag`` link whose ``entity_type`` is ``cms_post`` or
   ``cms_page``, ensure the matching ``cms_post_term(post_id, term_id)`` link
   exists (term resolved by slug).
3. Remove the now-migrated cms_post-scoped catalog data — the cms_post / cms_page
   ``vbwd_entity_tag`` links and the ``parent_entity_type='cms_post'``
   ``vbwd_tag`` rows — so tags are not duplicated across both systems. Tags
   scoped to OTHER entity types (products etc.) are left untouched.

Idempotent + set-based: ``ON CONFLICT DO NOTHING`` upserts make a re-run safe.

down() is BEST-EFFORT: it re-folds the restored cms_term('tag') rows + links
back into the cms_post-scoped core catalog (mirrors the original fold's
upgrade). It cannot reconstruct catalog rows for other entity types and is
provided for graph reversibility, not as a lossless rollback.

Revision ID: 20260618_unfold_tags
Revises: 20260617_cms_pw_config_override
Create Date: 2026-06-18

A CMS-plugin migration. Chains linearly off the current cms head
(``20260617_cms_pw_config_override``) and becomes the new cms head. The core
``vbwd_tag`` / ``vbwd_entity_tag`` tables it reads are guaranteed present via the
earlier ``20260613_1300_fold_tags`` merge node (anchored on the core tags
revision), so this revision never strands the graph for any plugin subset.
"""
from alembic import op
import sqlalchemy as sa


revision = "20260618_unfold_tags"
down_revision = "20260617_cms_pw_config_override"
branch_labels = None
depends_on = None

TAG_TERM_TYPE = "tag"
CMS_SCOPE = "cms_post"
CMS_ENTITY_TYPES = ("cms_post", "cms_page")


def upgrade() -> None:
    conn = op.get_bind()

    # 1. Restore the tag TERMS: each cms_post-scoped vbwd_tag becomes a
    #    cms_term('tag') (carry slug + name). ON CONFLICT keeps an existing
    #    (term_type, slug) — idempotent.
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
        {"tag_type": TAG_TERM_TYPE, "scope": CMS_SCOPE},
    )

    # 2. Restore the LINKS: each cms_post/cms_page entity_tag becomes a
    #    cms_post_term(post_id=entity_id, term_id=<term by slug>).
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
             WHERE link.entity_type IN :entity_types
            ON CONFLICT (post_id, term_id) DO NOTHING
            """
        ).bindparams(sa.bindparam("entity_types", expanding=True)),
        {"tag_type": TAG_TERM_TYPE, "entity_types": list(CMS_ENTITY_TYPES)},
    )

    # 3. Remove the migrated core-catalog data so tags aren't duplicated across
    #    both systems: first the cms_post/cms_page entity_tag links, then the
    #    cms_post-scoped tag rows. Other entity types are left untouched.
    conn.execute(
        sa.text(
            """
            DELETE FROM vbwd_entity_tag
             WHERE entity_type IN :entity_types
            """
        ).bindparams(sa.bindparam("entity_types", expanding=True)),
        {"entity_types": list(CMS_ENTITY_TYPES)},
    )
    conn.execute(
        sa.text("DELETE FROM vbwd_tag WHERE parent_entity_type = :scope"),
        {"scope": CMS_SCOPE},
    )


def downgrade() -> None:
    """Best-effort reverse: re-fold the cms_term tags back into the core catalog.

    Recreates a cms_post-scoped vbwd_tag for every cms_term('tag') and rebuilds
    the cms_post-scoped vbwd_entity_tag links from cms_post_term. It does NOT
    delete the recreated cms_term tag rows/links (a later up() removes the core
    rows again), and cannot restore catalog rows for non-cms entity types.
    """
    conn = op.get_bind()

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
        {"scope": CMS_SCOPE, "tag_type": TAG_TERM_TYPE},
    )

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
        {"entity_type": CMS_SCOPE, "tag_type": TAG_TERM_TYPE},
    )
