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
