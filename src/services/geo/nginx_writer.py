"""GeoBlockNginxWriter — publish the geo-block config as JSON for the fe-user
nginx njs handler (S120.1).

The fe-user nginx serves public pages statically, so a browser opening ``/``
never reaches the Flask geo-block middleware (S120). To enforce geo-blocking at
the layer that actually serves the page, an njs handler in the fe-user nginx
reads a small JSON descriptor from the shared ``${VAR_DIR}/cms/nginx/`` mount.
This writer regenerates that descriptor on every admin save so the allowed
country set and the toggles stay live — the njs handler re-reads the file and
nginx is never reloaded.

The JSON is written through the plugin filespace's ``ATOMIC_REPLACE`` policy
(temp file in the same directory + fsync + ``os.replace``), so a concurrent njs
read never sees a truncated file (``project_plugins_json_atomic_write_race``).

The bypass-cookie secret is a dedicated random hex value persisted in the plugin
filespace — NOT the app ``JWT_SECRET_KEY``. Spreading the application secret into
an nginx-readable file would widen its blast radius; the geo-bypass cookie gets
its own secret instead. It is generated once and reused so bypass cookies stay
valid across restarts.
"""
import secrets
from typing import Any, Dict

# Frozen output contract (the njs handler is built against these exact paths).
GEO_BLOCK_RELATIVE_PATH = "nginx/geo-block.json"
BYPASS_SECRET_RELATIVE_PATH = "nginx/bypass-secret"

# 32 random bytes → a 64-char hex secret for the bypass-cookie HMAC.
BYPASS_SECRET_BYTES = 32


class GeoBlockNginxWriter:
    """Writes the geo-block descriptor the fe-user nginx njs handler consumes."""

    def __init__(self, service, filespace) -> None:
        self._service = service
        self._filespace = filespace

    def bypass_secret(self) -> str:
        """Return the dedicated bypass secret, generating + persisting it once.

        Stable across restarts (read back from the plugin filespace) so a minted
        bypass cookie stays valid. Never falls back to the app JWT secret.
        """
        if self._filespace.exists(BYPASS_SECRET_RELATIVE_PATH):
            existing = (
                self._filespace.read_text(BYPASS_SECRET_RELATIVE_PATH) or ""
            ).strip()
            if existing:
                return existing
        secret = secrets.token_hex(BYPASS_SECRET_BYTES)
        self._filespace.write_text(BYPASS_SECRET_RELATIVE_PATH, secret)
        return secret

    def build_payload(self) -> Dict[str, Any]:
        """Assemble the frozen JSON payload from the live config + enabled set."""
        config = self._service.get_config()
        return {
            "enabled": bool(config.is_enabled),
            "allowed_codes": sorted(self._service.allowed_codes()),
            "bypass_query": config.bypass_query or "",
            "bypass_cookie_ttl_days": int(config.bypass_cookie_ttl_days),
            "blocked_target_slug": config.blocked_target_slug or "",
            "block_unknown_country": bool(config.block_unknown_country),
            "bypass_secret": self.bypass_secret(),
        }

    def write(self) -> Dict[str, Any]:
        """Atomically (re)write the geo-block descriptor; return what was written."""
        payload = self.build_payload()
        self._filespace.write_json(GEO_BLOCK_RELATIVE_PATH, payload)
        return payload
