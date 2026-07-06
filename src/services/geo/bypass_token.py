"""Signed geo-bypass token (S120).

Value = ``base64url(exp_ts).hmac_sha256(secret, exp_ts)``. Verification recomputes
the HMAC and checks the expiry is in the future; a tampered or expired token is
treated as invalid (i.e. absent). Forgery-proof: without ``secret`` an attacker
cannot produce a matching signature.
"""
import base64
import hashlib
import hmac
import time
from typing import Optional


class GeoBypassTokenSigner:
    """Mints and verifies HMAC-signed bypass tokens over an expiry timestamp."""

    def __init__(self, secret: str) -> None:
        self._secret = (secret or "").encode("utf-8")

    def sign(self, ttl_days: int) -> str:
        """Return a token valid for ``ttl_days`` from now."""
        expires_at = int(time.time()) + int(ttl_days) * 86400
        return self._encode(expires_at)

    def verify(self, token: Optional[str]) -> bool:
        """Return True only for an untampered, unexpired token."""
        if not token or "." not in token:
            return False
        payload, _, signature = token.partition(".")
        expires_at = self._decode_payload(payload)
        if expires_at is None:
            return False
        expected = self._sign_payload(str(expires_at))
        if not hmac.compare_digest(expected, signature):
            return False
        return expires_at > int(time.time())

    def _encode(self, expires_at: int) -> str:
        payload = (
            base64.urlsafe_b64encode(str(expires_at).encode("utf-8"))
            .decode("ascii")
            .rstrip("=")
        )
        return f"{payload}.{self._sign_payload(str(expires_at))}"

    def _decode_payload(self, payload: str) -> Optional[int]:
        try:
            padding = "=" * (-len(payload) % 4)
            raw = base64.urlsafe_b64decode(payload + padding)
            return int(raw.decode("utf-8"))
        except (ValueError, TypeError):
            return None

    def _sign_payload(self, expires_at_text: str) -> str:
        return hmac.new(
            self._secret, expires_at_text.encode("utf-8"), hashlib.sha256
        ).hexdigest()
