"""Integration: POST /api/v1/admin/cms/routing-rules/bulk (real PG).

Bulk-delete for CMS routing rules: the body carries ``{"ids": [...]}``; the
route returns ``{"deleted": N}``. Guarded by auth + admin + ``cms.configure``.
Seeded through the repository (no raw SQL). Mirrors the layouts bulk-delete
contract.

Engineering requirements (binding, restated): TDD-first; DevOps-first (cold
local + CI via the shared ``db`` fixture, no raw SQL); SOLID/DI/DRY; Liskov;
clean code; no overengineering. Quality guard:
``bin/pre-commit-check.sh --plugin cms --full``.
"""
import uuid

import pytest

from plugins.cms.src.models.cms_routing_rule import CmsRoutingRule
from plugins.cms.src.repositories.routing_rule_repository import (
    CmsRoutingRuleRepository,
)


@pytest.fixture
def admin_headers(client, db):
    resp = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@example.com", "password": "AdminPass123@"},
    )
    data = resp.get_json()
    token = data.get("token") or data.get("access_token")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def user_headers(client, db):
    resp = client.post(
        "/api/v1/auth/login",
        json={"email": "test@example.com", "password": "TestPass123@"},
    )
    data = resp.get_json()
    token = data.get("token") or data.get("access_token")
    return {"Authorization": f"Bearer {token}"}


def _seed_rule(db, **overrides):
    data = dict(
        name="Rule",
        match_type="language",
        match_value=f"de-{uuid.uuid4().hex[:6]}",
        target_slug="home-de",
        redirect_code=302,
        layer="middleware",
    )
    data.update(overrides)
    return CmsRoutingRuleRepository(db.session).save(CmsRoutingRule(**data))


class TestBulkDeleteRoutingRulesRoute:
    def test_bulk_delete_returns_count(self, client, db, admin_headers):
        rule_a_id = str(_seed_rule(db).id)
        rule_b_id = str(_seed_rule(db).id)
        resp = client.post(
            "/api/v1/admin/cms/routing-rules/bulk",
            json={"ids": [rule_a_id, rule_b_id]},
            headers=admin_headers,
        )
        assert resp.status_code == 200, resp.get_data(as_text=True)
        assert resp.get_json() == {"deleted": 2}
        repo = CmsRoutingRuleRepository(db.session)
        assert repo.find_by_id(rule_a_id) is None
        assert repo.find_by_id(rule_b_id) is None

    def test_unknown_id_is_skipped(self, client, db, admin_headers):
        rule_id = str(_seed_rule(db).id)
        resp = client.post(
            "/api/v1/admin/cms/routing-rules/bulk",
            json={"ids": [rule_id, str(uuid.uuid4())]},
            headers=admin_headers,
        )
        assert resp.status_code == 200
        assert resp.get_json() == {"deleted": 1}

    def test_missing_ids_returns_400(self, client, db, admin_headers):
        resp = client.post(
            "/api/v1/admin/cms/routing-rules/bulk",
            json={},
            headers=admin_headers,
        )
        assert resp.status_code == 400

    def test_non_list_ids_returns_400(self, client, db, admin_headers):
        resp = client.post(
            "/api/v1/admin/cms/routing-rules/bulk",
            json={"ids": "not-a-list"},
            headers=admin_headers,
        )
        assert resp.status_code == 400

    def test_requires_auth(self, client, db):
        resp = client.post(
            "/api/v1/admin/cms/routing-rules/bulk",
            json={"ids": []},
        )
        assert resp.status_code == 401

    def test_rejects_non_admin(self, client, db, user_headers):
        resp = client.post(
            "/api/v1/admin/cms/routing-rules/bulk",
            json={"ids": []},
            headers=user_headers,
        )
        assert resp.status_code == 403
