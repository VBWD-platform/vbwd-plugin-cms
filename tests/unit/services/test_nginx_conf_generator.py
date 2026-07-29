"""Unit: NginxConfGenerator — the generated snippet must be validated in the
context it is actually included into.

``generate()`` emits ``geo``/``map`` blocks. Those are ``http``-context
directives, so the snippet is a *fragment*: it is ``include``d inside the
``http {}`` block of the real config, and it is not a valid main config on its
own. Handing the bare fragment to ``nginx -t -c`` therefore always fails with
``"geo" directive is not allowed here`` on any machine that has nginx
installed, while machines without nginx skip validation entirely
(FileNotFoundError). That asymmetry is why this only ever broke in CI, where
the GitHub runner ships nginx.

These tests pin the fix: whatever is handed to ``nginx -t`` is a complete main
config wrapping the fragment, and the file written to the target path stays the
bare fragment (the real config includes it, so a wrapper there would nest
``http`` inside ``http``).

Engineering requirements (binding, restated): TDD-first; DevOps-first (cold
local + CI); SOLID/DI/DRY; clean code; no overengineering. Quality guard:
``bin/pre-commit-check.sh --plugin cms --full``.
"""
import os
import subprocess

import pytest

from plugins.cms.src.services.routing.nginx_conf_generator import (
    NginxConfGenerator,
    NginxConfInvalidError,
)


class _Rule:
    def __init__(self, match_type, match_value, target_slug):
        self.match_type = match_type
        self.match_value = match_value
        self.target_slug = target_slug


def _fragment() -> str:
    return NginxConfGenerator().generate(
        [
            _Rule("ip_range", "10.0.0.0/8", "de"),
            _Rule("language", "de", "de"),
        ],
        default_slug="en",
    )


def test_fragment_alone_is_not_a_valid_main_config():
    """Guards the premise: the snippet really does need a wrapper."""
    fragment = _fragment()
    assert "geo $remote_addr" in fragment
    assert "events" not in fragment
    assert "http {" not in fragment


def test_validation_wraps_the_fragment_in_a_full_config(tmp_path, monkeypatch):
    """What reaches ``nginx -t`` must be a complete main config."""
    validated: dict[str, str] = {}

    def _fake_run(argv, **kwargs):
        assert argv[0] == "nginx"
        with open(argv[argv.index("-c") + 1]) as handle:
            validated["conf"] = handle.read()
        return subprocess.CompletedProcess(argv, 0, b"", b"")

    monkeypatch.setattr(subprocess, "run", _fake_run)

    target = tmp_path / "cms_routing.conf"
    NginxConfGenerator().write_and_validate(_fragment(), str(target))

    conf = validated["conf"]
    assert "events {" in conf, "nginx needs an events section in a main config"
    assert "http {" in conf, "geo/map are http-context directives"
    # The fragment itself must be inside the http block, not merely appended.
    assert conf.index("http {") < conf.index("geo $remote_addr")
    assert conf.rstrip().endswith("}")


def test_written_file_is_the_bare_fragment_not_the_wrapper(tmp_path, monkeypatch):
    """The wrapper exists only to validate; the real config includes the
    fragment inside its own ``http`` block."""
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda argv, **kwargs: subprocess.CompletedProcess(argv, 0, b"", b""),
    )

    target = tmp_path / "cms_routing.conf"
    fragment = _fragment()
    NginxConfGenerator().write_and_validate(fragment, str(target))

    written = target.read_text()
    assert written == fragment
    assert "events {" not in written
    assert "http {" not in written


def test_invalid_conf_still_raises(tmp_path, monkeypatch):
    """Wrapping must not neuter the check — a real nginx error still raises."""
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda argv, **kwargs: subprocess.CompletedProcess(
            argv, 1, b"", b'nginx: [emerg] unexpected "}"'
        ),
    )

    target = tmp_path / "cms_routing.conf"
    with pytest.raises(NginxConfInvalidError):
        NginxConfGenerator().write_and_validate(_fragment(), str(target))
    # A rejected conf must not land on the target path.
    assert not os.path.exists(target)


def test_missing_nginx_is_not_an_error(tmp_path, monkeypatch):
    """Dev machines without nginx skip validation and still write."""

    def _raise(argv, **kwargs):
        raise FileNotFoundError("nginx")

    monkeypatch.setattr(subprocess, "run", _raise)

    target = tmp_path / "cms_routing.conf"
    NginxConfGenerator().write_and_validate(_fragment(), str(target))
    assert target.read_text() == _fragment()
