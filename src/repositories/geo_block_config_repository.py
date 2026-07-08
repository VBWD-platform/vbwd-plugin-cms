"""Repository for the singleton CmsGeoBlockConfig row (S120)."""
from typing import Optional

from plugins.cms.src.models.cms_geo_block_config import CmsGeoBlockConfig


class CmsGeoBlockConfigRepository:
    """Get-or-create access to the single geo-block settings row."""

    def __init__(self, session) -> None:
        self.session = session

    def get(self) -> Optional[CmsGeoBlockConfig]:
        """Read the singleton config without creating it (read-only hot path).

        The enforcement middleware runs on every request and must not create /
        commit a row as a side effect of a read — get-or-create commits on the
        create path, which expires the freshly created instance and forces a
        second SELECT when the caller then reads a column.
        """
        return self.session.query(CmsGeoBlockConfig).first()

    def get_or_create(self) -> CmsGeoBlockConfig:
        config = self.session.query(CmsGeoBlockConfig).first()
        if config is None:
            config = CmsGeoBlockConfig()
            self.session.add(config)
            self.session.commit()
        return config

    def save(self, config: CmsGeoBlockConfig) -> CmsGeoBlockConfig:
        self.session.add(config)
        self.session.commit()
        return config
