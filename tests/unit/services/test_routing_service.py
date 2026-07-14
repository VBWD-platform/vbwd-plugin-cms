"""Unit tests for CmsRoutingService."""
import pytest
from unittest.mock import MagicMock
from datetime import datetime, timezone

from plugins.cms.src.models.cms_routing_rule import CmsRoutingRule
from plugins.cms.src.services.routing.routing_service import (
    CmsRoutingService,
    CmsRoutingRuleNotFoundError,
)
from plugins.cms.src.services.routing.nginx_conf_generator import NginxConfGenerator
from plugins.cms.src.services.routing.nginx_reload_gateway import StubNginxReloadGateway
from plugins.cms.src.services.routing.matchers import RequestContext


def _make_rule(**kwargs):
    r = CmsRoutingRule()
    r.id = kwargs.get("id", "test-id-1")
    from uuid import uuid4

    r.id = uuid4()
    r.name = kwargs.get("name", "Test Rule")
    r.is_active = kwargs.get("is_active", True)
    r.priority = kwargs.get("priority", 0)
    r.match_type = kwargs.get("match_type", "language")
    r.match_value = kwargs.get("match_value", "de")
    r.target_slug = kwargs.get("target_slug", "home-de")
    r.redirect_code = kwargs.get("redirect_code", 302)
    r.is_rewrite = kwargs.get("is_rewrite", False)
    r.layer = kwargs.get("layer", "middleware")
    r.created_at = datetime(2026, 3, 15, tzinfo=timezone.utc)
    r.updated_at = datetime(2026, 3, 15, tzinfo=timezone.utc)
    return r


def _make_service(rules=None):
    rule_repo = MagicMock()
    store = {str(r.id): r for r in (rules or [])}

    rule_repo.find_all.return_value = list(store.values())
    rule_repo.find_all_active.return_value = [r for r in store.values() if r.is_active]
    rule_repo.find_all_active_for_layer.side_effect = lambda layer: [
        r for r in store.values() if r.is_active and r.layer == layer
    ]
    rule_repo.find_by_id.side_effect = lambda rid: store.get(str(rid))

    def _save(rule):
        store[str(rule.id)] = rule
        return rule

    rule_repo.save.side_effect = _save

    def _delete(rule_id):
        key = str(rule_id)
        if key in store:
            del store[key]
            return True
        return False

    rule_repo.delete.side_effect = _delete

    def _delete_many(ids):
        count = 0
        for rule_id in ids:
            key = str(rule_id)
            if key in store:
                del store[key]
                count += 1
        return count

    rule_repo.delete_many.side_effect = _delete_many

    nginx_gw = StubNginxReloadGateway()
    conf_gen = NginxConfGenerator()
    svc = CmsRoutingService(
        rule_repo=rule_repo,
        conf_generator=conf_gen,
        nginx_gateway=nginx_gw,
        config={
            "routing": {
                "nginx_conf_path": "/tmp/test_cms_routing.conf",
                "default_slug": "home",
            }
        },
    )
    return svc, rule_repo, nginx_gw


# ── list_rules ────────────────────────────────────────────────────────────────


def test_list_rules_returns_dicts():
    rule = _make_rule()
    svc, _, _ = _make_service([rule])
    result = svc.list_rules()
    assert len(result) == 1
    assert result[0]["name"] == "Test Rule"


# ── create_rule ───────────────────────────────────────────────────────────────


def test_create_rule_valid():
    svc, repo, _ = _make_service()
    data = {
        "name": "Lang DE",
        "match_type": "language",
        "match_value": "de",
        "target_slug": "home-de",
    }
    result = svc.create_rule(data)
    assert result["name"] == "Lang DE"
    repo.save.assert_called_once()


def test_create_rule_invalid_match_type():
    svc, _, _ = _make_service()
    with pytest.raises(ValueError, match="match_type"):
        svc.create_rule(
            {
                "name": "Bad",
                "match_type": "invalid",
                "target_slug": "home",
            }
        )


def test_create_rule_invalid_redirect_code():
    svc, _, _ = _make_service()
    with pytest.raises(ValueError, match="redirect_code"):
        svc.create_rule(
            {
                "name": "Bad",
                "match_type": "language",
                "match_value": "de",
                "target_slug": "home",
                "redirect_code": 200,
            }
        )


# ── update_rule ───────────────────────────────────────────────────────────────


def test_update_rule_updates_fields():
    rule = _make_rule(name="Old Name")
    svc, repo, _ = _make_service([rule])
    result = svc.update_rule(str(rule.id), {"name": "New Name"})
    assert result["name"] == "New Name"


def test_update_rule_not_found():
    svc, _, _ = _make_service()
    with pytest.raises(CmsRoutingRuleNotFoundError):
        svc.update_rule("nonexistent-id", {"name": "X"})


# ── delete_rule ───────────────────────────────────────────────────────────────


def test_delete_rule_success():
    rule = _make_rule()
    svc, repo, _ = _make_service([rule])
    svc.delete_rule(str(rule.id))
    repo.delete.assert_called_once_with(str(rule.id))


def test_delete_rule_not_found():
    svc, _, _ = _make_service()
    with pytest.raises(CmsRoutingRuleNotFoundError):
        svc.delete_rule("nonexistent-id")


# ── bulk_delete ───────────────────────────────────────────────────────────────


def test_bulk_delete_returns_count():
    rule_a = _make_rule(layer="middleware")
    rule_b = _make_rule(layer="middleware")
    svc, repo, nginx_gw = _make_service([rule_a, rule_b])
    result = svc.bulk_delete([str(rule_a.id), str(rule_b.id)])
    assert result == {"deleted": 2}
    repo.delete_many.assert_called_once_with([str(rule_a.id), str(rule_b.id)])


def test_bulk_delete_skips_unknown_ids():
    rule = _make_rule(layer="middleware")
    svc, _, _ = _make_service([rule])
    result = svc.bulk_delete([str(rule.id), "nonexistent-id"])
    assert result == {"deleted": 1}


def test_bulk_delete_syncs_nginx_once_when_nginx_rule_deleted():
    nginx_rule = _make_rule(layer="nginx", match_type="language", match_value="de")
    mw_rule = _make_rule(layer="middleware")
    svc, _, nginx_gw = _make_service([nginx_rule, mw_rule])
    svc.bulk_delete([str(nginx_rule.id), str(mw_rule.id)])
    # Exactly one reload for the whole batch, never once-per-rule.
    assert nginx_gw.reload_count == 1


def test_bulk_delete_does_not_sync_when_only_middleware_rules():
    mw_a = _make_rule(layer="middleware")
    mw_b = _make_rule(layer="middleware")
    svc, _, nginx_gw = _make_service([mw_a, mw_b])
    svc.bulk_delete([str(mw_a.id), str(mw_b.id)])
    assert nginx_gw.reload_count == 0


def test_bulk_delete_empty_list_returns_zero_no_sync():
    nginx_rule = _make_rule(layer="nginx")
    svc, repo, nginx_gw = _make_service([nginx_rule])
    result = svc.bulk_delete([])
    assert result == {"deleted": 0}
    assert nginx_gw.reload_count == 0


# ── evaluate ─────────────────────────────────────────────────────────────────


def test_evaluate_returns_instruction():
    rule = _make_rule(match_type="language", match_value="de", target_slug="home-de")
    svc, _, _ = _make_service([rule])
    ctx = RequestContext(
        path="/",
        accept_language="de-DE,de;q=0.9",
        remote_addr="127.0.0.1",
        geoip_country=None,
        cookie_lang=None,
    )
    instruction = svc.evaluate(ctx)
    assert instruction is not None
    assert instruction.location == "/home-de"


def test_evaluate_no_match_returns_none():
    rule = _make_rule(match_type="language", match_value="de", target_slug="home-de")
    svc, _, _ = _make_service([rule])
    ctx = RequestContext(
        path="/",
        accept_language="fr-FR",
        remote_addr="127.0.0.1",
        geoip_country=None,
        cookie_lang=None,
    )
    instruction = svc.evaluate(ctx)
    assert instruction is None
