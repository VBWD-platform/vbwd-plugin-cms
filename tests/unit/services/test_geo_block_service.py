"""Unit tests for CmsGeoBlockService (S120, T4). Repos are mocked — no DB.

Engineering requirements (binding, restated): TDD-first; DevOps-first; SOLID/DI/
DRY; Liskov; clean code; no overengineering. Quality guard:
``bin/pre-commit-check.sh --plugin cms --full``.
"""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from plugins.cms.src.models.cms_geo_block_config import CmsGeoBlockConfig
from plugins.cms.src.services.geo.geo_block_service import CmsGeoBlockService


def _country(code, enabled=True):
    return SimpleNamespace(code=code, is_enabled=enabled)


def _service(config=None, enabled_countries=None):
    # DB-level column defaults only apply on INSERT; an unpersisted instance
    # needs its fields set explicitly for the mocked (no-DB) service path.
    if config is None:
        config = CmsGeoBlockConfig(
            is_enabled=False,
            bypass_query="",
            bypass_cookie_ttl_days=30,
            blocked_target_slug="/locked",
            block_unknown_country=False,
        )
    config_repo = MagicMock()
    config_repo.get_or_create.return_value = config
    config_repo.save.side_effect = lambda c: c
    country_repo = MagicMock()
    country_repo.find_enabled.return_value = enabled_countries or []
    return CmsGeoBlockService(config_repo=config_repo, country_repo=country_repo)


def test_allowed_codes_derives_from_core_enabled_countries():
    service = _service(
        enabled_countries=[_country("de"), _country("AT"), _country("ch")]
    )
    assert service.allowed_codes() == {"DE", "AT", "CH"}


def test_config_dict_includes_allowed_country_summary():
    service = _service(enabled_countries=[_country("de"), _country("fr")])
    result = service.config_dict()
    assert result["allowed_country_codes"] == ["DE", "FR"]
    assert result["allowed_country_count"] == 2
    assert result["is_enabled"] is False


def test_update_normalizes_bypass_query_leading_separators():
    config = CmsGeoBlockConfig()
    service = _service(config=config)
    service.update_config({"bypass_query": "?allowme=yes"})
    assert config.bypass_query == "allowme=yes"


def test_update_rejects_bypass_query_with_multiple_pairs():
    service = _service()
    with pytest.raises(ValueError):
        service.update_config({"bypass_query": "a=1&b=2"})


def test_update_rejects_bypass_query_without_value():
    service = _service()
    with pytest.raises(ValueError):
        service.update_config({"bypass_query": "allowme"})


def test_update_allows_empty_bypass_query():
    config = CmsGeoBlockConfig(bypass_query="allowme=yes")
    service = _service(config=config)
    service.update_config({"bypass_query": ""})
    assert config.bypass_query == ""


def test_update_rejects_non_positive_ttl():
    service = _service()
    with pytest.raises(ValueError):
        service.update_config({"bypass_cookie_ttl_days": 0})


def test_update_rejects_slug_without_leading_slash():
    service = _service()
    with pytest.raises(ValueError):
        service.update_config({"blocked_target_slug": "locked"})


def test_update_allows_empty_slug_for_451():
    config = CmsGeoBlockConfig()
    service = _service(config=config)
    service.update_config({"blocked_target_slug": ""})
    assert config.blocked_target_slug == ""


def test_update_coerces_boolean_toggles():
    config = CmsGeoBlockConfig()
    service = _service(config=config)
    service.update_config({"is_enabled": True, "block_unknown_country": True})
    assert config.is_enabled is True
    assert config.block_unknown_country is True
