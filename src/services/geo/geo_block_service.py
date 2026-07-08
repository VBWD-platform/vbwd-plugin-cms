"""CmsGeoBlockService — singleton config + derived allowed-country set (S120).

The allowed ISO set is derived live from core ``vbwd_country.is_enabled`` (the
tax-and-countries screen), never duplicated here (DRY). The service owns config
get/update with validation; enforcement lives in ``CmsGeoBlockMiddleware``.
"""
import re
from typing import Any, Dict, Optional, Set

from plugins.cms.src.models.cms_geo_block_config import CmsGeoBlockConfig


# A single ``key=value`` with no query separators or whitespace.
_BYPASS_QUERY_RE = re.compile(r"^[^=&?\s]+=[^=&?\s]+$")


class CmsGeoBlockService:
    """Config CRUD + derived allowed-country codes for CMS geo-blocking."""

    def __init__(self, config_repo, country_repo) -> None:
        self._config_repo = config_repo
        self._country_repo = country_repo

    def get_config(self) -> CmsGeoBlockConfig:
        return self._config_repo.get_or_create()

    def get_config_readonly(self) -> Optional[CmsGeoBlockConfig]:
        """Return the singleton config, or ``None`` if never configured.

        For the per-request enforcement path, which must not create/commit a
        row as a side effect of a read. A missing row means geo-blocking was
        never set up — equivalent to disabled — so the caller passes through.
        """
        return self._config_repo.get()

    def allowed_codes(self) -> Set[str]:
        """Derive the enabled ISO country codes from core (upper-case)."""
        return {
            country.code.upper()
            for country in self._country_repo.find_enabled()
            if country.code
        }

    def config_dict(self) -> Dict[str, Any]:
        """The config plus the read-only allowed-country summary for the tab."""
        codes = sorted(self.allowed_codes())
        return {
            **self.get_config().to_dict(),
            "allowed_country_codes": codes,
            "allowed_country_count": len(codes),
        }

    def update_config(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Validate + persist provided fields; return the fresh config dict."""
        config = self.get_config()

        if "is_enabled" in data:
            config.is_enabled = bool(data["is_enabled"])
        if "block_unknown_country" in data:
            config.block_unknown_country = bool(data["block_unknown_country"])
        if "bypass_query" in data:
            config.bypass_query = self._validate_bypass_query(data["bypass_query"])
        if "bypass_cookie_ttl_days" in data:
            config.bypass_cookie_ttl_days = self._validate_ttl_days(
                data["bypass_cookie_ttl_days"]
            )
        if "blocked_target_slug" in data:
            config.blocked_target_slug = self._validate_target_slug(
                data["blocked_target_slug"]
            )

        self._config_repo.save(config)
        return self.config_dict()

    @staticmethod
    def normalize_bypass_query(raw: str) -> str:
        """Strip leading ``?``/``&`` and surrounding whitespace."""
        return (raw or "").strip().lstrip("?&").strip()

    def _validate_bypass_query(self, raw: Any) -> str:
        normalized = self.normalize_bypass_query(str(raw))
        if normalized and not _BYPASS_QUERY_RE.match(normalized):
            raise ValueError(
                "bypass_query must be a single key=value (e.g. allowme=yes)"
            )
        return normalized

    @staticmethod
    def _validate_ttl_days(raw: Any) -> int:
        try:
            ttl_days = int(raw)
        except (TypeError, ValueError):
            raise ValueError("bypass_cookie_ttl_days must be a positive integer")
        if ttl_days <= 0:
            raise ValueError("bypass_cookie_ttl_days must be a positive integer")
        return ttl_days

    @staticmethod
    def _validate_target_slug(raw: Any) -> str:
        slug = (str(raw) if raw is not None else "").strip()
        if slug and not slug.startswith("/"):
            raise ValueError("blocked_target_slug must start with '/' when set")
        return slug
