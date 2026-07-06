"""Repository for the singleton CmsGeoBlockConfig row (S120)."""
from plugins.cms.src.models.cms_geo_block_config import CmsGeoBlockConfig


class CmsGeoBlockConfigRepository:
    """Get-or-create access to the single geo-block settings row."""

    def __init__(self, session) -> None:
        self.session = session

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
