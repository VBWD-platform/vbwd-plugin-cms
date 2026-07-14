"""Integration: CmsRoutingRuleRepository.delete_many (real PG).

``delete_many`` deletes every row whose id is in the given list in ONE commit,
returns the count actually removed, and silently skips unknown ids (not an
error). Seeded through the repository (no raw SQL).

Engineering requirements (binding, restated): TDD-first; DevOps-first (cold
local + CI via the shared ``db`` fixture, no raw SQL); SOLID/DI/DRY; Liskov;
clean code; no overengineering. Quality guard:
``bin/pre-commit-check.sh --plugin cms --full``.
"""
import uuid

from plugins.cms.src.models.cms_routing_rule import CmsRoutingRule
from plugins.cms.src.repositories.routing_rule_repository import (
    CmsRoutingRuleRepository,
)


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


class TestDeleteMany:
    def test_deletes_given_ids_and_returns_count(self, db):
        rule_a_id = str(_seed_rule(db).id)
        rule_b_id = str(_seed_rule(db).id)
        keep_id = str(_seed_rule(db).id)
        repo = CmsRoutingRuleRepository(db.session)

        deleted = repo.delete_many([rule_a_id, rule_b_id])

        assert deleted == 2
        assert repo.find_by_id(rule_a_id) is None
        assert repo.find_by_id(rule_b_id) is None
        # Untargeted rule survives.
        assert repo.find_by_id(keep_id) is not None

    def test_skips_unknown_ids(self, db):
        rule_id = str(_seed_rule(db).id)
        repo = CmsRoutingRuleRepository(db.session)

        deleted = repo.delete_many([rule_id, str(uuid.uuid4())])

        assert deleted == 1
        assert repo.find_by_id(rule_id) is None

    def test_empty_list_returns_zero(self, db):
        repo = CmsRoutingRuleRepository(db.session)
        assert repo.delete_many([]) == 0
