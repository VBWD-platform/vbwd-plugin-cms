"""S150 unit — the default ``robots.txt`` policy keeps CMS content crawlable.

``build_default_robots_txt(site_base)`` is a pure function: no Flask, no
config store. These tests pin the target body and evaluate it two ways:

  * an RFC 9309 **longest-match** evaluator (``*`` wildcard, ``$`` end
    anchor, ties go to ``Allow``) — the reference every major crawler follows;
  * the stdlib ``urllib.robotparser`` (first-match, no ``$``) — a guard for
    naïve crawlers on the "never blocks CMS surfaces" contract.

Engineering requirements (binding, restated): TDD-first (RED before the
policy module existed); DevOps-first; SOLID (the policy text has one home);
DI (the base URL is an argument); DRY; Liskov (override / ``seo.mode=off``
untouched); clean code; no overengineering. Guard:
``bin/pre-commit-check.sh --plugin cms --full``.
"""
import re
from urllib.robotparser import RobotFileParser

import pytest

from plugins.cms.src.services.seo_robots_policy import build_default_robots_txt

SITE_BASE = "https://example.com"
ANY_AGENT = "AnyBot"

CMS_SURFACES = [
    "/",
    "/blog",
    "/blog/some-post",
    "/admin-guide",
    "/dashboard-tips",
    "/uploads/x.png",
    "/assets/app.js",
    "/sitemap.xml",
    "/api/v1/cms/posts/about",
    "/api/v1/cms/rss",
]

PRIVATE_SURFACES = [
    "/dashboard",
    "/dashboard/invoices",
    "/admin/",
    "/admin/users",
    "/api/v1/auth/login",
    "/api/v1/user/profile",
]


def _pattern_to_regex(pattern: str) -> "re.Pattern[str]":
    """Translate an RFC 9309 path pattern (``*``, trailing ``$``) to a regex."""
    anchored = pattern.endswith("$")
    body = pattern[:-1] if anchored else pattern
    regex = ".*".join(re.escape(segment) for segment in body.split("*"))
    return re.compile(regex + ("$" if anchored else ""))


def _is_allowed_longest_match(robots_body: str, path: str) -> bool:
    """RFC 9309 §2.2.2: the longest matching rule wins; a tie goes to Allow."""
    best_length = -1
    best_allows = True
    for line in robots_body.splitlines():
        directive, _, value = line.partition(":")
        directive = directive.strip().lower()
        pattern = value.strip()
        if directive not in ("allow", "disallow") or not pattern:
            continue
        if not _pattern_to_regex(pattern).match(path):
            continue
        allows = directive == "allow"
        if len(pattern) > best_length or (len(pattern) == best_length and allows):
            best_length = len(pattern)
            best_allows = allows
    return best_allows


def _is_allowed_stdlib(robots_body: str, path: str) -> bool:
    parser = RobotFileParser()
    parser.parse(robots_body.splitlines())
    return parser.can_fetch(ANY_AGENT, SITE_BASE + path)


def _lines() -> list:
    return build_default_robots_txt(SITE_BASE).splitlines()


def test_default_allows_public_cms_api():
    assert "Allow: /api/v1/cms/" in _lines()


def test_default_blocks_private_api_only_under_trailing_slash():
    lines = _lines()
    assert "Disallow: /api/" in lines
    assert "Disallow: /api" not in lines


def test_default_admin_block_has_trailing_slash():
    lines = _lines()
    assert "Disallow: /admin/" in lines
    assert "Disallow: /admin" not in lines


def test_default_dashboard_is_anchored():
    lines = _lines()
    assert "Disallow: /dashboard$" in lines
    assert "Disallow: /dashboard/" in lines
    assert "Disallow: /dashboard" not in lines


@pytest.mark.parametrize("path", CMS_SURFACES)
def test_default_never_blocks_cms_surfaces(path):
    body = build_default_robots_txt(SITE_BASE)
    assert _is_allowed_longest_match(body, path)
    assert _is_allowed_stdlib(body, path)


@pytest.mark.parametrize("path", PRIVATE_SURFACES)
def test_default_blocks_private_surfaces(path):
    assert not _is_allowed_longest_match(build_default_robots_txt(SITE_BASE), path)


def test_sitemap_line_uses_given_base():
    body = build_default_robots_txt("http://localhost:8080/")
    assert "Sitemap: http://localhost:8080/sitemap.xml" in body.splitlines()
