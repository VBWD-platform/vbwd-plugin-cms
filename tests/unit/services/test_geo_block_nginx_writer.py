"""Unit: GeoBlockNginxWriter — the config→JSON writer the fe-user nginx njs
handler reads (S120.1, T1).

The fe-user nginx serves public pages statically, so a browser never reaches the
Flask geo-block middleware (S120). The njs handler enforces the block by reading
``${VAR_DIR}/cms/nginx/geo-block.json``; this writer regenerates that descriptor
on every admin save. These tests pin the frozen JSON shape (the njs handler is
built against these exact keys), the atomic write (temp + ``os.replace`` — no
torn read), the derived allowed-country set, and the dedicated persisted bypass
secret (stable across writes, generated once, never the app JWT secret).

Engineering requirements (binding, restated): TDD-first; DevOps-first (cold local
+ CI); SOLID/DI/DRY; Liskov (fakes honour the service contract); clean code; no
overengineering. Quality guard: ``bin/pre-commit-check.sh --plugin cms --full``.
"""
import json
import os

from plugins.cms.src.services.geo.nginx_writer import (
    BYPASS_SECRET_BYTES,
    GEO_BLOCK_RELATIVE_PATH,
    GeoBlockNginxWriter,
)
from vbwd.services.filesystem.local import LocalFilesystemManager


_FROZEN_KEYS = {
    "enabled",
    "allowed_codes",
    "bypass_query",
    "bypass_cookie_ttl_days",
    "blocked_target_slug",
    "block_unknown_country",
    "bypass_secret",
}


class _FakeConfig:
    """Structural stand-in for CmsGeoBlockConfig (Liskov: same read surface)."""

    def __init__(
        self,
        is_enabled=True,
        bypass_query="allowme=yes",
        bypass_cookie_ttl_days=30,
        blocked_target_slug="/locked",
        block_unknown_country=False,
    ):
        self.is_enabled = is_enabled
        self.bypass_query = bypass_query
        self.bypass_cookie_ttl_days = bypass_cookie_ttl_days
        self.blocked_target_slug = blocked_target_slug
        self.block_unknown_country = block_unknown_country


class _FakeService:
    """Honours the CmsGeoBlockService surface the writer depends on."""

    def __init__(self, config, allowed_codes):
        self._config = config
        self._allowed_codes = set(allowed_codes)

    def get_config(self):
        return self._config

    def allowed_codes(self):
        return set(self._allowed_codes)


def _build(tmp_path, config, allowed_codes):
    manager = LocalFilesystemManager(var_root=str(tmp_path))
    writer = GeoBlockNginxWriter(
        service=_FakeService(config, allowed_codes),
        filespace=manager.for_plugin("cms"),
    )
    return writer, manager


def _read_written(tmp_path):
    path = tmp_path / "cms" / GEO_BLOCK_RELATIVE_PATH
    return json.loads(path.read_text())


def test_write_produces_the_frozen_json_shape(tmp_path):
    config = _FakeConfig(
        is_enabled=True,
        bypass_query="allowme=yes",
        bypass_cookie_ttl_days=30,
        blocked_target_slug="/locked",
        block_unknown_country=False,
    )
    writer, _ = _build(tmp_path, config, ["DE", "AT"])

    returned = writer.write()
    on_disk = _read_written(tmp_path)

    assert on_disk == returned
    assert set(on_disk.keys()) == _FROZEN_KEYS
    assert on_disk["enabled"] is True
    assert on_disk["allowed_codes"] == ["AT", "DE"]
    assert on_disk["bypass_query"] == "allowme=yes"
    assert on_disk["bypass_cookie_ttl_days"] == 30
    assert on_disk["blocked_target_slug"] == "/locked"
    assert on_disk["block_unknown_country"] is False
    assert isinstance(on_disk["bypass_secret"], str) and on_disk["bypass_secret"]


def test_allowed_codes_reflects_enabled_countries_sorted(tmp_path):
    writer, _ = _build(tmp_path, _FakeConfig(), ["FR", "DE", "AT"])

    payload = writer.write()

    assert payload["allowed_codes"] == ["AT", "DE", "FR"]


def test_disabled_config_still_writes_enabled_false(tmp_path):
    writer, _ = _build(tmp_path, _FakeConfig(is_enabled=False), ["DE"])

    writer.write()

    assert _read_written(tmp_path)["enabled"] is False


def test_bypass_secret_is_hex_and_stable_across_two_writes(tmp_path):
    writer, _ = _build(tmp_path, _FakeConfig(), ["DE"])

    first = writer.write()["bypass_secret"]
    second = writer.write()["bypass_secret"]

    assert first == second
    int(first, 16)  # a valid hex string
    assert len(first) == BYPASS_SECRET_BYTES * 2


def test_bypass_secret_stable_across_writer_instances(tmp_path):
    writer_one, manager = _build(tmp_path, _FakeConfig(), ["DE"])
    first = writer_one.write()["bypass_secret"]

    writer_two = GeoBlockNginxWriter(
        service=_FakeService(_FakeConfig(), ["DE"]),
        filespace=manager.for_plugin("cms"),
    )
    second = writer_two.write()["bypass_secret"]

    assert first == second


def test_write_is_atomic_via_os_replace_no_leftover_temp(tmp_path, monkeypatch):
    from vbwd.services.filesystem import local as local_fs

    replace_targets = []
    real_replace = os.replace

    def _spy_replace(source, destination):
        replace_targets.append(destination)
        return real_replace(source, destination)

    monkeypatch.setattr(local_fs.os, "replace", _spy_replace)

    writer, _ = _build(tmp_path, _FakeConfig(), ["DE"])
    writer.write()

    assert any(str(target).endswith("geo-block.json") for target in replace_targets)
    nginx_dir = tmp_path / "cms" / "nginx"
    leftovers = [entry.name for entry in nginx_dir.iterdir() if entry.suffix == ".tmp"]
    assert leftovers == []
