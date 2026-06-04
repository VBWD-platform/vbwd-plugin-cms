"""CMS plugin CLI commands (S47.0).

Registered on the Flask app from the plugin's ``on_enable`` via
``current_app.cli.add_command`` — core stays agnostic (it declares no cms
command). Idempotent: safe to run on every deploy after ``flask db upgrade``.

    flask cms backfill        # cms_page -> cms_post(page), cms_category -> term
"""
import click
from flask import current_app
from flask.cli import with_appcontext


@click.group("cms")
def cms_cli() -> None:
    """CMS plugin maintenance commands."""


@cms_cli.command("backfill")
@with_appcontext
def backfill_command() -> None:
    """Fold live cms_page / cms_category rows into the unified model.

    Idempotent — a second run creates nothing new. Copies (does not delete)
    so the legacy tables stay intact for the one-release migration window.
    """
    from vbwd.extensions import db
    from plugins.cms.src.repositories.cms_page_repository import CmsPageRepository
    from plugins.cms.src.repositories.cms_category_repository import (
        CmsCategoryRepository,
    )
    from plugins.cms.src.repositories.post_repository import PostRepository
    from plugins.cms.src.repositories.term_repository import TermRepository
    from plugins.cms.src.repositories.routing_rule_repository import (
        CmsRoutingRuleRepository,
    )
    from plugins.cms.src.services.cms_backfill_service import CmsBackfillService

    event_dispatcher = getattr(current_app, "event_dispatcher", None)
    service = CmsBackfillService(
        page_repo=CmsPageRepository(db.session),
        category_repo=CmsCategoryRepository(db.session),
        post_repo=PostRepository(db.session),
        term_repo=TermRepository(db.session),
        event_dispatcher=event_dispatcher,
        routing_repo=CmsRoutingRuleRepository(db.session),
    )
    summary = service.backfill()

    click.echo("CMS backfill complete:")
    click.echo(f"  pages copied:      {summary['pages_copied']}")
    click.echo(f"  pages skipped:     {summary['pages_skipped']}")
    click.echo(f"  categories copied: {summary['categories_copied']}")
    click.echo(f"  categories skipped:{summary['categories_skipped']}")
