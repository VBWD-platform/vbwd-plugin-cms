"""CmsRoutingService — rule CRUD, middleware evaluation, nginx conf sync."""
from typing import List, Optional, Dict, Any

from plugins.cms.src.models.cms_routing_rule import CmsRoutingRule
from plugins.cms.src.services.routing.matchers import (
    RequestContext,
    RedirectInstruction,
    matcher_for,
)
from plugins.cms.src.services.routing.nginx_conf_generator import (
    NginxConfGenerator,
    NginxConfInvalidError,
)
from plugins.cms.src.services.routing.nginx_reload_gateway import (
    SubprocessNginxReloadGateway,
)


class CmsRoutingRuleNotFoundError(Exception):
    pass


class CmsRoutingService:
    VALID_MATCH_TYPES = {
        "default",
        "language",
        "ip_range",
        "country",
        "path_prefix",
        "cookie",
    }
    VALID_REDIRECT_CODES = {301, 302}
    VALID_LAYERS = {"nginx", "middleware"}

    def __init__(
        self,
        rule_repo,
        conf_generator: NginxConfGenerator,
        nginx_gateway,
        config: Dict[str, Any],
    ) -> None:
        self._rule_repo = rule_repo
        self._conf_generator = conf_generator
        self._nginx_gateway = nginx_gateway
        self._config = config

    # ── Admin CRUD ────────────────────────────────────────────────────────────

    def list_rules(self) -> List[Dict]:
        return [r.to_dict() for r in self._rule_repo.find_all()]

    def create_rule(self, data: Dict) -> Dict:
        self._validate(data, require_all=True)
        rule = CmsRoutingRule(
            name=data["name"],
            is_active=data.get("is_active", True),
            priority=int(data.get("priority", 0)),
            match_type=data["match_type"],
            match_value=data.get("match_value"),
            target_slug=data["target_slug"],
            redirect_code=int(data.get("redirect_code", 302)),
            is_rewrite=bool(data.get("is_rewrite", False)),
            layer=data.get("layer", "middleware"),
        )
        self._rule_repo.save(rule)
        if rule.layer == "nginx":
            self.sync_nginx()
        return rule.to_dict()

    def update_rule(self, rule_id: str, data: Dict) -> Dict:
        rule = self._rule_repo.find_by_id(rule_id)
        if not rule:
            raise CmsRoutingRuleNotFoundError(rule_id)
        self._validate(data, require_all=False)
        updatable = (
            "name",
            "is_active",
            "priority",
            "match_type",
            "match_value",
            "target_slug",
            "redirect_code",
            "is_rewrite",
            "layer",
        )
        for field in updatable:
            if field in data:
                setattr(rule, field, data[field])
        self._rule_repo.save(rule)
        if rule.layer == "nginx":
            self.sync_nginx()
        return rule.to_dict()

    def delete_rule(self, rule_id: str) -> None:
        rule = self._rule_repo.find_by_id(rule_id)
        if not rule:
            raise CmsRoutingRuleNotFoundError(rule_id)
        was_nginx = rule.layer == "nginx"
        deleted = self._rule_repo.delete(rule_id)
        if not deleted:
            raise CmsRoutingRuleNotFoundError(rule_id)
        if was_nginx:
            self.sync_nginx()

    # ── Nginx sync ────────────────────────────────────────────────────────────

    def sync_nginx(self) -> None:
        routing_cfg = self._config.get("routing", {})
        conf_path = routing_cfg.get(
            "nginx_conf_path", "/etc/nginx/conf.d/cms_routing.conf"
        )
        default_slug = routing_cfg.get("default_slug", "home1")
        rules = self._rule_repo.find_all_active_for_layer("nginx")
        conf_str = self._conf_generator.generate(rules, default_slug)
        try:
            self._conf_generator.write_and_validate(conf_str, conf_path)
        except NginxConfInvalidError:
            raise
        self._nginx_gateway.reload()

    # ── Middleware evaluation ─────────────────────────────────────────────────

    def evaluate(self, ctx: RequestContext) -> Optional[RedirectInstruction]:
        rules = self._rule_repo.find_all_active_for_layer("middleware")
        for rule in rules:
            m = matcher_for(rule.match_type)
            if m and m.matches(rule, ctx):
                location = (
                    rule.target_slug
                    if rule.target_slug.startswith("/")
                    else f"/{rule.target_slug}"
                )
                return RedirectInstruction(
                    location=location,
                    code=rule.redirect_code,
                    is_rewrite=rule.is_rewrite,
                )
        return None

    # ── Validation ────────────────────────────────────────────────────────────

    def _validate(self, data: Dict, require_all: bool) -> None:
        errors = []
        if require_all or "match_type" in data:
            mt = data.get("match_type", "")
            if mt not in self.VALID_MATCH_TYPES:
                errors.append(
                    f"match_type must be one of {sorted(self.VALID_MATCH_TYPES)}"
                )
        if require_all or "redirect_code" in data:
            rc = int(data.get("redirect_code", 302))
            if rc not in self.VALID_REDIRECT_CODES:
                errors.append("redirect_code must be 301 or 302")
        if require_all or "target_slug" in data:
            if not data.get("target_slug", "").strip():
                errors.append("target_slug must not be empty")
        if require_all or "priority" in data:
            try:
                p = int(data.get("priority", 0))
                if p < 0:
                    errors.append("priority must be a non-negative integer")
            except (TypeError, ValueError):
                errors.append("priority must be an integer")
        if require_all or "layer" in data:
            layer = data.get("layer", "middleware")
            if layer not in self.VALID_LAYERS:
                errors.append(f"layer must be one of {sorted(self.VALID_LAYERS)}")
        if errors:
            raise ValueError("; ".join(errors))
