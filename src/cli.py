"""CLI commands for the cms plugin (S120.1).

Registered on the live app's click group at plugin enable
(``current_app.cli.add_command`` — core stays agnostic and declares no plugin
commands). ``flask cms geo-block sync`` regenerates
``${VAR_DIR}/cms/nginx/geo-block.json`` so the fe-user nginx njs handler picks up
the current enabled-country list and toggles WITHOUT a geo-block config PUT — the
allowed set is derived from core ``vbwd_country.is_enabled`` and can change (via
the tax-and-countries screen) independently of the geo-block config.
"""
import json

import click
from flask.cli import with_appcontext


@click.group("cms")
def cms_cli() -> None:
    """CMS plugin maintenance commands."""


@cms_cli.command("repair-permalinks")
@click.option(
    "--apply",
    "apply_changes",
    is_flag=True,
    default=False,
    help="Persist the repairs + emit old→new 301 redirects. Without this flag "
    "the command is a DRY RUN and writes nothing.",
)
@click.option(
    "--type",
    "post_type",
    default="post",
    show_default=True,
    help="Post type to repair (only the engine-managed 'post' type today).",
)
@with_appcontext
def repair_permalinks(apply_changes: bool, post_type: str) -> None:
    """Collapse accumulated post permalinks back to a single prefix.

    Recomputes each engine-managed post's slug via the SAME renderer used on save,
    fixing rows whose stored slug accumulated repeated prefixes before the
    recursion fix. DRY RUN by default (prints what WOULD change and writes
    nothing); pass ``--apply`` to write and emit old→new 301 redirects. Idempotent
    and non-destructive — rows already correct are skipped and a recomputed slug
    that would collide with a different post is reported, not forced.
    """
    from plugins.cms.src.routes import _post_service

    result = _post_service().repair_permalinks(post_type=post_type, apply=apply_changes)

    change_label = "CHANGED" if apply_changes else "WOULD-CHANGE"
    for change in result["changes"]:
        click.echo(f"{change_label} {change['old_slug']} -> {change['new_slug']}")
    for collision in result["collisions"]:
        click.echo(
            f"SKIP-COLLISION {collision['new_slug']} "
            f"(collides with post {collision['collides_with']})"
        )
    count_key = "changed" if apply_changes else "would_change"
    click.echo(
        f"scanned={result['scanned']} "
        f"{count_key}={len(result['changes'])} "
        f"already_correct={result['already_correct']} "
        f"skipped_collision={len(result['collisions'])}"
    )


@cms_cli.group("geo-block")
def geo_block_cli() -> None:
    """Geo-block enforcement descriptor commands."""


@geo_block_cli.command("sync")
@with_appcontext
def geo_block_sync() -> None:
    """Regenerate the fe-user nginx geo-block JSON from the current config."""
    from plugins.cms.src.services.geo.geo_block_wiring import build_geo_block_writer

    payload = build_geo_block_writer().write()
    click.echo(
        json.dumps(
            {
                "written": "cms/nginx/geo-block.json",
                "enabled": payload["enabled"],
                "allowed_codes": payload["allowed_codes"],
            }
        )
    )
