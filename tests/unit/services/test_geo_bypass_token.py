"""Unit tests for GeoBypassTokenSigner (S120, T3).

Engineering requirements (binding, restated): TDD-first; DevOps-first; SOLID/DI/
DRY; Liskov; clean code; no overengineering. Quality guard:
``bin/pre-commit-check.sh --plugin cms --full``.
"""
from plugins.cms.src.services.geo.bypass_token import GeoBypassTokenSigner


SECRET = "unit-test-secret"


def test_sign_verify_round_trip():
    signer = GeoBypassTokenSigner(SECRET)
    token = signer.sign(ttl_days=30)
    assert signer.verify(token) is True


def test_tampered_signature_is_invalid():
    signer = GeoBypassTokenSigner(SECRET)
    token = signer.sign(ttl_days=30)
    payload, _, signature = token.partition(".")
    tampered = f"{payload}.{'0' * len(signature)}"
    assert signer.verify(tampered) is False


def test_tampered_payload_is_invalid():
    signer = GeoBypassTokenSigner(SECRET)
    token = signer.sign(ttl_days=30)
    _, _, signature = token.partition(".")
    # A different expiry with the original signature must fail.
    import base64

    forged_payload = base64.urlsafe_b64encode(b"9999999999").decode("ascii").rstrip("=")
    assert signer.verify(f"{forged_payload}.{signature}") is False


def test_expired_token_is_invalid():
    signer = GeoBypassTokenSigner(SECRET)
    # Negative TTL ⇒ expiry already in the past.
    token = signer.sign(ttl_days=-1)
    assert signer.verify(token) is False


def test_wrong_secret_rejects_token():
    minted = GeoBypassTokenSigner(SECRET).sign(ttl_days=30)
    assert GeoBypassTokenSigner("other-secret").verify(minted) is False


def test_empty_or_malformed_token_is_invalid():
    signer = GeoBypassTokenSigner(SECRET)
    assert signer.verify(None) is False
    assert signer.verify("") is False
    assert signer.verify("no-dot-here") is False
