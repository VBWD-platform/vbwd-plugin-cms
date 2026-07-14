"""CmsRoutingRule repository."""
from typing import List, Optional
from plugins.cms.src.models.cms_routing_rule import CmsRoutingRule


class CmsRoutingRuleRepository:
    def __init__(self, session) -> None:
        self.session = session

    def find_all(self) -> List[CmsRoutingRule]:
        return (
            self.session.query(CmsRoutingRule)
            .order_by(CmsRoutingRule.priority.asc(), CmsRoutingRule.created_at.asc())
            .all()
        )

    def find_all_active(self) -> List[CmsRoutingRule]:
        return (
            self.session.query(CmsRoutingRule)
            .filter(CmsRoutingRule.is_active.is_(True))
            .order_by(CmsRoutingRule.priority.asc(), CmsRoutingRule.created_at.asc())
            .all()
        )

    def find_all_active_for_layer(self, layer: str) -> List[CmsRoutingRule]:
        return (
            self.session.query(CmsRoutingRule)
            .filter(
                CmsRoutingRule.is_active.is_(True),
                CmsRoutingRule.layer == layer,
            )
            .order_by(CmsRoutingRule.priority.asc(), CmsRoutingRule.created_at.asc())
            .all()
        )

    def find_by_match(
        self, match_type: str, match_value: Optional[str]
    ) -> List[CmsRoutingRule]:
        """All rules with the given (match_type, match_value).

        Used by the permalink engine to emit an *idempotent* 301 on a slug
        rename — it checks whether a rule already redirects the old path before
        creating a new one (S122).
        """
        return (
            self.session.query(CmsRoutingRule)
            .filter(
                CmsRoutingRule.match_type == match_type,
                CmsRoutingRule.match_value == match_value,
            )
            .all()
        )

    def find_by_id(self, rule_id: str) -> Optional[CmsRoutingRule]:
        return (
            self.session.query(CmsRoutingRule)
            .filter(CmsRoutingRule.id == rule_id)
            .first()
        )

    def save(self, rule: CmsRoutingRule) -> CmsRoutingRule:
        self.session.add(rule)
        self.session.commit()
        return rule

    def delete(self, rule_id: str) -> bool:
        rule = self.find_by_id(rule_id)
        if not rule:
            return False
        self.session.delete(rule)
        self.session.commit()
        return True

    def delete_many(self, ids: List[str]) -> int:
        """Delete every rule whose id is in ``ids`` in one commit.

        Returns the count actually deleted; unknown ids are skipped (not an
        error). Empty ``ids`` is a no-op that returns 0.
        """
        if not ids:
            return 0
        deleted = (
            self.session.query(CmsRoutingRule)
            .filter(CmsRoutingRule.id.in_(ids))
            .delete(synchronize_session=False)
        )
        self.session.commit()
        return deleted
