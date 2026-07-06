"""Geo-block service + nginx-writer factories (S120 / S120.1).

One home for constructing the ``CmsGeoBlockService`` (from the singleton config
repo + core ``CountryRepository``) and the ``GeoBlockNginxWriter`` (service +
the plugin's ``cms`` filespace). Both the admin routes and the ``flask cms
geo-block sync`` CLI resolve their collaborators here (DRY), so there is a single
wiring definition for the request path, the CLI path, and any future caller.
"""


def build_geo_block_service():
    """Build the geo-block config service bound to the live request session."""
    from vbwd.extensions import db
    from vbwd.repositories.country_repository import CountryRepository
    from plugins.cms.src.repositories.geo_block_config_repository import (
        CmsGeoBlockConfigRepository,
    )
    from plugins.cms.src.services.geo.geo_block_service import CmsGeoBlockService

    return CmsGeoBlockService(
        config_repo=CmsGeoBlockConfigRepository(db.session),
        country_repo=CountryRepository(db.session),
    )


def build_geo_block_writer():
    """Build the writer that publishes ``cms/nginx/geo-block.json`` for nginx."""
    from flask import current_app
    from plugins.cms.src.services.geo.nginx_writer import GeoBlockNginxWriter

    filespace = current_app.container.filesystem_manager().for_plugin("cms")
    return GeoBlockNginxWriter(
        service=build_geo_block_service(),
        filespace=filespace,
    )
