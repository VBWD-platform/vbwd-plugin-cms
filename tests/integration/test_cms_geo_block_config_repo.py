"""Integration: CmsGeoBlockConfig singleton repo (S120, T1), real PG.

Data flows through the repository (no raw SQL). The shared ``db`` fixture builds
the schema (create_all) and rolls each test back.

Engineering requirements (binding, restated): TDD-first; DevOps-first (cold local
+ CI); SOLID/DI/DRY; Liskov; clean code; no overengineering. Quality guard:
``bin/pre-commit-check.sh --plugin cms --full``.
"""
from plugins.cms.src.repositories.geo_block_config_repository import (
    CmsGeoBlockConfigRepository,
)


def test_get_or_create_returns_defaults(db):
    config = CmsGeoBlockConfigRepository(db.session).get_or_create()
    assert config.is_enabled is False
    assert config.bypass_query == ""
    assert config.bypass_cookie_ttl_days == 30
    assert config.blocked_target_slug == "/locked"
    assert config.block_unknown_country is False


def test_get_or_create_is_singleton(db):
    repo = CmsGeoBlockConfigRepository(db.session)
    first = repo.get_or_create()
    second = repo.get_or_create()
    assert str(first.id) == str(second.id)


def test_save_persists_changes(db):
    repo = CmsGeoBlockConfigRepository(db.session)
    config = repo.get_or_create()
    config.is_enabled = True
    config.bypass_query = "allowme=yes"
    repo.save(config)

    db.session.expire_all()
    reloaded = repo.get_or_create()
    assert reloaded.is_enabled is True
    assert reloaded.bypass_query == "allowme=yes"
