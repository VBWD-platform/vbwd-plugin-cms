"""GeoIpResolver — resolves the request's country to ISO-3166-1 alpha-2 (S120).

Fills the dormant ``g.geoip_country`` gap the routing subsystem already models
(``CountryMatcher``). Source order:

1. An optional trusted country header (e.g. ``CF-IPCountry``) when configured —
   off by default (vbwd.cc is Cloudflare grey-cloud/DNS-only, no such header).
2. A MaxMind GeoLite2-Country ``.mmdb`` lookup on the trusted client IP.

The client IP is taken from the trusted hop of ``X-Forwarded-For`` (only our own
host-nginx is in front). A missing/unreadable DB fails open: the resolver returns
``None`` and logs a single warning — geo-blocking then never locks the world out.
"""
import logging
from typing import Any, Callable, Optional

from flask import request


logger = logging.getLogger(__name__)

# Sentinel country codes MaxMind/CF emit for unresolvable clients.
_UNKNOWN_HEADER_VALUES = {"", "XX", "T1", "ZZ"}


def _default_reader_factory(mmdb_path: str) -> Any:
    """Open a MaxMind reader. Imported lazily so the heavy dep is optional.

    ``geoip2`` is installed from the plugin's ``requirements.txt`` at runtime; a
    missing package (or DB file) raises here and the resolver fails open.
    """
    import geoip2.database

    return geoip2.database.Reader(mmdb_path)


class GeoIpResolver:
    """Resolves the caller's country once per request (fail-open on error)."""

    def __init__(
        self,
        mmdb_path: str,
        trusted_header: Optional[str] = None,
        trusted_proxy_count: int = 1,
        reader_factory: Optional[Callable[[str], Any]] = None,
    ) -> None:
        self._mmdb_path = mmdb_path
        self._trusted_header = trusted_header
        self._trusted_proxy_count = max(1, int(trusted_proxy_count))
        self._reader_factory = reader_factory or _default_reader_factory
        self._reader = None
        self._reader_open_attempted = False

    def resolve_country(self) -> Optional[str]:
        """Return the caller's upper-case ISO country code, or ``None``."""
        header_country = self._from_trusted_header()
        if header_country is not None:
            return header_country
        return self._lookup(self._client_ip())

    def _from_trusted_header(self) -> Optional[str]:
        if not self._trusted_header:
            return None
        value = (request.headers.get(self._trusted_header) or "").strip().upper()
        if value in _UNKNOWN_HEADER_VALUES:
            return None
        return value

    def _client_ip(self) -> Optional[str]:
        forwarded_for = request.headers.get("X-Forwarded-For")
        if forwarded_for:
            hops = [hop.strip() for hop in forwarded_for.split(",") if hop.strip()]
            if hops:
                index = max(0, len(hops) - self._trusted_proxy_count)
                return hops[index]
        return request.remote_addr

    def _lookup(self, client_ip: Optional[str]) -> Optional[str]:
        if not client_ip:
            return None
        reader = self._get_reader()
        if reader is None:
            return None
        try:
            response = reader.country(client_ip)
        except Exception:
            # Private/unknown IP (AddressNotFoundError) or a lookup error: the
            # site must not lock out on it — treat as unknown, no warning spam.
            return None
        code = getattr(getattr(response, "country", None), "iso_code", None)
        return code.upper() if code else None

    def _get_reader(self):
        if self._reader_open_attempted:
            return self._reader
        self._reader_open_attempted = True
        try:
            self._reader = self._reader_factory(self._mmdb_path)
        except Exception as exc:
            logger.warning(
                "CMS geo-block: GeoLite2 DB unavailable at %s (%s); "
                "geo-blocking fails open.",
                self._mmdb_path,
                exc,
            )
            self._reader = None
        return self._reader
