"""CmsGeoBlockConfig model — singleton geo-blocking settings (S120).

One row per instance (get-or-create). Off by default so a fresh deploy never
locks anyone out. The allowed-country ISO set is NOT stored here — it is derived
live from core ``vbwd_country.is_enabled`` (DRY; the tax-and-countries screen is
the single source). See ``CmsGeoBlockService``.
"""
from vbwd.extensions import db
from vbwd.models.base import BaseModel


DEFAULT_BLOCKED_TARGET_SLUG = "/locked"
DEFAULT_BYPASS_COOKIE_TTL_DAYS = 30


class CmsGeoBlockConfig(BaseModel):
    """Singleton settings row for CMS country geo-blocking."""

    __tablename__ = "cms_geo_block_config"

    # Master switch. Off ⇒ the geo-block middleware is a pure no-op.
    is_enabled = db.Column(db.Boolean, default=False, nullable=False)

    # Normalized ``key=value`` (no leading ``?``/``&``). Empty ⇒ bypass disabled.
    bypass_query = db.Column(db.String(255), default="", nullable=False)

    # Lifetime of the minted bypass cookie, in days.
    bypass_cookie_ttl_days = db.Column(
        db.Integer, default=DEFAULT_BYPASS_COOKIE_TTL_DAYS, nullable=False
    )

    # CMS page a blocked visitor is redirected to. Empty ⇒ respond 451 instead.
    blocked_target_slug = db.Column(
        db.String(255), default=DEFAULT_BLOCKED_TARGET_SLUG, nullable=False
    )

    # When geo cannot resolve a country: False = fail-open (pass), True = block.
    block_unknown_country = db.Column(db.Boolean, default=False, nullable=False)

    def to_dict(self):
        return {
            "id": str(self.id),
            "is_enabled": self.is_enabled,
            "bypass_query": self.bypass_query or "",
            "bypass_cookie_ttl_days": self.bypass_cookie_ttl_days,
            "blocked_target_slug": self.blocked_target_slug or "",
            "block_unknown_country": self.block_unknown_country,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }
