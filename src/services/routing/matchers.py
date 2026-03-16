"""IRuleMatcher implementations for CMS routing rules."""
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class RequestContext:
    path: str
    accept_language: str
    remote_addr: str
    geoip_country: Optional[str]
    cookie_lang: Optional[str]


@dataclass(frozen=True)
class RedirectInstruction:
    location: str
    code: int
    is_rewrite: bool


class DefaultMatcher:
    def matches(self, rule, ctx: RequestContext) -> bool:
        return rule.match_type == "default"


class LanguageMatcher:
    def matches(self, rule, ctx: RequestContext) -> bool:
        if rule.match_type != "language":
            return False
        target_lang = (rule.match_value or "").lower()
        if ctx.cookie_lang and ctx.cookie_lang.lower() == target_lang:
            return True
        header_lang = ctx.accept_language[:2].lower() if ctx.accept_language else ""
        return header_lang == target_lang


class IpRangeMatcher:
    def matches(self, rule, ctx: RequestContext) -> bool:
        if rule.match_type != "ip_range":
            return False
        import ipaddress
        try:
            return ipaddress.ip_address(ctx.remote_addr) in ipaddress.ip_network(
                rule.match_value or "", strict=False
            )
        except ValueError:
            return False


class CountryMatcher:
    def matches(self, rule, ctx: RequestContext) -> bool:
        if rule.match_type != "country" or not ctx.geoip_country:
            return False
        countries = [c.strip().upper() for c in (rule.match_value or "").split(",")]
        return ctx.geoip_country.upper() in countries


class PathPrefixMatcher:
    def matches(self, rule, ctx: RequestContext) -> bool:
        if rule.match_type != "path_prefix":
            return False
        return ctx.path.startswith(rule.match_value or "")


class CookieMatcher:
    def matches(self, rule, ctx: RequestContext) -> bool:
        if rule.match_type != "cookie":
            return False
        k, _, v = (rule.match_value or "").partition("=")
        return ctx.cookie_lang == v.strip() if k.strip() == "vbwd_lang" else False


_MATCHERS = {
    "default": DefaultMatcher(),
    "language": LanguageMatcher(),
    "ip_range": IpRangeMatcher(),
    "country": CountryMatcher(),
    "path_prefix": PathPrefixMatcher(),
    "cookie": CookieMatcher(),
}


def matcher_for(match_type: str):
    return _MATCHERS.get(match_type)
