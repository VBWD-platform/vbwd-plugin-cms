"""Unit tests for CMS routing rule matchers."""
import pytest
from unittest.mock import MagicMock
from plugins.cms.src.services.routing.matchers import (
    RequestContext,
    DefaultMatcher,
    LanguageMatcher,
    IpRangeMatcher,
    CountryMatcher,
    PathPrefixMatcher,
    CookieMatcher,
    matcher_for,
)


def _rule(match_type, match_value=None):
    r = MagicMock()
    r.match_type = match_type
    r.match_value = match_value
    return r


def _ctx(
    path="/",
    accept_language="en-US,en;q=0.9",
    remote_addr="127.0.0.1",
    geoip_country=None,
    cookie_lang=None,
):
    return RequestContext(
        path=path,
        accept_language=accept_language,
        remote_addr=remote_addr,
        geoip_country=geoip_country,
        cookie_lang=cookie_lang,
    )


# ── DefaultMatcher ────────────────────────────────────────────────────────────

def test_default_matcher_matches():
    m = DefaultMatcher()
    assert m.matches(_rule("default"), _ctx()) is True


def test_default_matcher_wrong_type():
    m = DefaultMatcher()
    assert m.matches(_rule("language", "de"), _ctx()) is False


# ── LanguageMatcher ───────────────────────────────────────────────────────────

def test_language_matcher_by_accept_language():
    m = LanguageMatcher()
    ctx = _ctx(accept_language="de-DE,de;q=0.9")
    assert m.matches(_rule("language", "de"), ctx) is True


def test_language_matcher_by_cookie():
    m = LanguageMatcher()
    ctx = _ctx(accept_language="en", cookie_lang="de")
    assert m.matches(_rule("language", "de"), ctx) is True


def test_language_matcher_no_match():
    m = LanguageMatcher()
    ctx = _ctx(accept_language="fr-FR")
    assert m.matches(_rule("language", "de"), ctx) is False


def test_language_matcher_wrong_type():
    m = LanguageMatcher()
    assert m.matches(_rule("default"), _ctx()) is False


# ── IpRangeMatcher ────────────────────────────────────────────────────────────

def test_ip_range_matcher_in_range():
    m = IpRangeMatcher()
    ctx = _ctx(remote_addr="203.0.113.5")
    assert m.matches(_rule("ip_range", "203.0.113.0/24"), ctx) is True


def test_ip_range_matcher_out_of_range():
    m = IpRangeMatcher()
    ctx = _ctx(remote_addr="10.0.0.1")
    assert m.matches(_rule("ip_range", "203.0.113.0/24"), ctx) is False


def test_ip_range_matcher_invalid_ip():
    m = IpRangeMatcher()
    ctx = _ctx(remote_addr="not-an-ip")
    assert m.matches(_rule("ip_range", "203.0.113.0/24"), ctx) is False


# ── CountryMatcher ────────────────────────────────────────────────────────────

def test_country_matcher_single():
    m = CountryMatcher()
    ctx = _ctx(geoip_country="DE")
    assert m.matches(_rule("country", "DE"), ctx) is True


def test_country_matcher_multi():
    m = CountryMatcher()
    ctx = _ctx(geoip_country="AT")
    assert m.matches(_rule("country", "DE,AT,CH"), ctx) is True


def test_country_matcher_no_geoip():
    m = CountryMatcher()
    ctx = _ctx(geoip_country=None)
    assert m.matches(_rule("country", "DE"), ctx) is False


# ── PathPrefixMatcher ─────────────────────────────────────────────────────────

def test_path_prefix_matcher_matches():
    m = PathPrefixMatcher()
    ctx = _ctx(path="/old-pricing/plan-a")
    assert m.matches(_rule("path_prefix", "/old-pricing"), ctx) is True


def test_path_prefix_matcher_no_match():
    m = PathPrefixMatcher()
    ctx = _ctx(path="/pricing")
    assert m.matches(_rule("path_prefix", "/old-pricing"), ctx) is False


# ── CookieMatcher ─────────────────────────────────────────────────────────────

def test_cookie_matcher_matches():
    m = CookieMatcher()
    ctx = _ctx(cookie_lang="de")
    assert m.matches(_rule("cookie", "vbwd_lang=de"), ctx) is True


def test_cookie_matcher_no_match():
    m = CookieMatcher()
    ctx = _ctx(cookie_lang="en")
    assert m.matches(_rule("cookie", "vbwd_lang=de"), ctx) is False


# ── matcher_for ───────────────────────────────────────────────────────────────

def test_matcher_for_returns_correct_instance():
    assert isinstance(matcher_for("default"), DefaultMatcher)
    assert isinstance(matcher_for("language"), LanguageMatcher)
    assert isinstance(matcher_for("ip_range"), IpRangeMatcher)
    assert isinstance(matcher_for("country"), CountryMatcher)
    assert isinstance(matcher_for("path_prefix"), PathPrefixMatcher)
    assert isinstance(matcher_for("cookie"), CookieMatcher)


def test_matcher_for_unknown_returns_none():
    assert matcher_for("unknown_type") is None
