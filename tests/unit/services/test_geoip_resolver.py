"""Unit tests for GeoIpResolver (S120, T2). The reader is injected — no mmdb,
no network, no geoip2 install needed.

Engineering requirements (binding, restated): TDD-first; DevOps-first; SOLID/DI/
DRY; Liskov; clean code; no overengineering. Quality guard:
``bin/pre-commit-check.sh --plugin cms --full``.
"""
import logging
from unittest.mock import MagicMock

import pytest
from flask import Flask

from plugins.cms.src.services.geo.geoip_resolver import GeoIpResolver


@pytest.fixture
def app():
    application = Flask(__name__)
    application.config["TESTING"] = True
    return application


def _reader_returning(iso_code):
    reader = MagicMock()
    reader.country.return_value.country.iso_code = iso_code
    return reader


def test_mmdb_hit_sets_country(app):
    resolver = GeoIpResolver(
        mmdb_path="/db.mmdb",
        reader_factory=lambda _path: _reader_returning("de"),
    )
    with app.test_request_context("/", headers={"X-Forwarded-For": "203.0.113.7"}):
        assert resolver.resolve_country() == "DE"


def test_missing_db_returns_none_and_logs_one_warning(app, caplog):
    def _raise(_path):
        raise FileNotFoundError("missing")

    resolver = GeoIpResolver(mmdb_path="/missing.mmdb", reader_factory=_raise)
    with caplog.at_level(logging.WARNING):
        with app.test_request_context("/", headers={"X-Forwarded-For": "203.0.113.7"}):
            assert resolver.resolve_country() is None
        # Second request must not re-warn (open attempted only once).
        with app.test_request_context("/", headers={"X-Forwarded-For": "203.0.113.7"}):
            assert resolver.resolve_country() is None
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 1
    assert "GeoLite2 DB unavailable" in warnings[0].getMessage()


def test_address_not_found_returns_none_without_warning(app, caplog):
    reader = MagicMock()
    reader.country.side_effect = ValueError("private ip")
    resolver = GeoIpResolver(mmdb_path="/db.mmdb", reader_factory=lambda _path: reader)
    with caplog.at_level(logging.WARNING):
        with app.test_request_context("/", headers={"X-Forwarded-For": "10.0.0.1"}):
            assert resolver.resolve_country() is None
    assert [r for r in caplog.records if r.levelno == logging.WARNING] == []


def test_trusted_header_source_used_when_configured(app):
    def _no_lookup(_path):
        raise AssertionError("mmdb reader must not be consulted")

    resolver = GeoIpResolver(
        mmdb_path="/db.mmdb",
        trusted_header="CF-IPCountry",
        reader_factory=_no_lookup,
    )
    with app.test_request_context("/", headers={"CF-IPCountry": "fr"}):
        assert resolver.resolve_country() == "FR"


def test_trusted_header_sentinel_falls_through_to_mmdb(app):
    resolver = GeoIpResolver(
        mmdb_path="/db.mmdb",
        trusted_header="CF-IPCountry",
        reader_factory=lambda _path: _reader_returning("us"),
    )
    with app.test_request_context(
        "/", headers={"CF-IPCountry": "XX", "X-Forwarded-For": "203.0.113.7"}
    ):
        assert resolver.resolve_country() == "US"


def test_trusted_hop_ip_extraction_ignores_spoofed_prefix(app):
    captured = {}

    def _factory(_path):
        reader = MagicMock()

        def _country(ip):
            captured["ip"] = ip
            response = MagicMock()
            response.country.iso_code = "DE"
            return response

        reader.country.side_effect = _country
        return reader

    resolver = GeoIpResolver(
        mmdb_path="/db.mmdb", trusted_proxy_count=1, reader_factory=_factory
    )
    with app.test_request_context(
        "/", headers={"X-Forwarded-For": "1.1.1.1, 203.0.113.9"}
    ):
        resolver.resolve_country()
    # Only our own proxy hop is trusted: the real client is the last entry,
    # not the spoofable leading value.
    assert captured["ip"] == "203.0.113.9"
