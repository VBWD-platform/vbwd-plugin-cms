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

    def find_by_id(self, rule_id: str) -> Optional[CmsRoutingRule]:
        return self.session.query(CmsRoutingRule).filter(CmsRoutingRule.id == rule_id).first()

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
