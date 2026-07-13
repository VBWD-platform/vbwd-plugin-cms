"""Unit tests for the ``flask cms repair-permalinks`` CLI wrapper.

The command is a thin shell over ``PostService.repair_permalinks`` (the DB-backed
logic is proven in ``tests/integration/test_cms_repair_permalinks.py``). Here a
fake service records how the command calls it, so we assert the CLI contract
without touching the database:

* dry-run is the DEFAULT — no ``--apply`` flag ⇒ ``apply=False`` (a prod write
  must be opted into explicitly);
* ``--apply`` flips the flag to ``True``;
* ``--type`` defaults to ``post`` and forwards an override;
* the summary reports scanned / would-change|changed / already-correct /
  skipped-collision.

Engineering requirements (binding, restated): TDD-first; DevOps-first; SOLID/DI/
DRY (one repair home in the service; the CLI only formats); Liskov; clean code;
no overengineering. Quality guard: ``bin/pre-commit-check.sh --plugin cms --full``.
"""
import plugins.cms.src.routes as cms_routes
from plugins.cms.src.cli import cms_cli


class _FakePostService:
    def __init__(self) -> None:
        self.calls = []

    def repair_permalinks(self, post_type: str = "post", apply: bool = False):
        self.calls.append({"post_type": post_type, "apply": apply})
        return {
            "post_type": post_type,
            "applied": apply,
            "scanned": 3,
            "changes": [
                {
                    "id": "post-1",
                    "old_slug": "blog/x/blog/x/foo",
                    "new_slug": "blog/x/foo",
                    "old_slug_base": "blog/x/foo",
                    "new_slug_base": "foo",
                }
            ],
            "already_correct": 1,
            "collisions": [
                {"id": "post-2", "new_slug": "blog/x/bar", "collides_with": "post-9"}
            ],
        }


def _invoke(app, monkeypatch, args):
    fake = _FakePostService()
    monkeypatch.setattr(cms_routes, "_post_service", lambda: fake)
    result = app.test_cli_runner().invoke(cms_cli, ["repair-permalinks", *args])
    return fake, result


def test_dry_run_is_default(app, monkeypatch):
    fake, result = _invoke(app, monkeypatch, [])
    assert result.exit_code == 0, result.output
    assert fake.calls == [{"post_type": "post", "apply": False}]
    assert "would_change=1" in result.output
    assert "blog/x/blog/x/foo -> blog/x/foo" in result.output
    assert "post-9" in result.output  # collision reported
    assert "scanned=3" in result.output
    assert "already_correct=1" in result.output
    assert "skipped_collision=1" in result.output


def test_apply_flag_writes(app, monkeypatch):
    fake, result = _invoke(app, monkeypatch, ["--apply"])
    assert result.exit_code == 0, result.output
    assert fake.calls == [{"post_type": "post", "apply": True}]
    assert "changed=1" in result.output


def test_type_option_forwarded(app, monkeypatch):
    fake, result = _invoke(app, monkeypatch, ["--type", "page"])
    assert result.exit_code == 0, result.output
    assert fake.calls == [{"post_type": "page", "apply": False}]
