"""Integration: S120 — a fresh seed yields a canonical ``index`` homepage.

The homepage-slug drift (index / home / home1) is consolidated onto a single
canonical slug ``index``. This suite runs the real seeder against PostgreSQL and
proves a fresh install renders ``/`` correctly with NO manual pages:

  * the seeded homepage post uses slug ``index`` (type ``page``, published);
  * NO ``home1`` page and NO ``default`` middleware routing rule is seeded (the
    fe renders the home post at ``/`` directly — a default redirect is harmful);
  * canonical-consolidation redirects ``/index → /`` and ``/home → /`` are seeded
    as ``path_exact`` 301 middleware rules (exact so ``/home`` never catches the
    ``/home2`` demo page);
  * the seeder is idempotent (a second run creates no duplicate rules).

The shared ``db`` fixture isolates this in a rolled-back transaction.

Engineering requirements (binding, restated): TDD-first; DevOps-first (real PG,
cold local + CI; demo data seeded through services); SOLID/DI/DRY; Liskov; clean
code; no overengineering. Quality guard: ``bin/pre-commit-check.sh --plugin cms
--full``.
"""
from plugins.cms.src.bin.populate_cms import populate_cms
from plugins.cms.src.models.cms_post import CmsPost, POST_STATUS_PUBLISHED
from plugins.cms.src.models.cms_routing_rule import CmsRoutingRule


def _routing_rule(db, **filters):
    return db.session.query(CmsRoutingRule).filter_by(**filters).one_or_none()


class TestSeedHomeSlugCanonical:
    def test_seed_yields_index_as_home_post(self, db):
        populate_cms()
        home = (
            db.session.query(CmsPost).filter_by(type="page", slug="index").one_or_none()
        )
        assert home is not None, "canonical home post 'index' not seeded"
        assert home.status == POST_STATUS_PUBLISHED
        assert home.title

    def test_seed_does_not_seed_home1_as_homepage(self, db):
        populate_cms()
        home1 = (
            db.session.query(CmsPost).filter_by(type="page", slug="home1").one_or_none()
        )
        assert home1 is None, "home1 must not be seeded as the homepage"

    def test_seed_creates_no_default_routing_rule(self, db):
        populate_cms()
        default_rule = _routing_rule(db, match_type="default", layer="middleware")
        assert default_rule is None, "the harmful default redirect rule must be gone"

    def test_seed_creates_index_and_home_301_redirects(self, db):
        populate_cms()
        index_redirect = _routing_rule(
            db, match_type="path_exact", match_value="/index"
        )
        assert index_redirect is not None, "/index → / redirect not seeded"
        assert index_redirect.target_slug == "/"
        assert index_redirect.redirect_code == 301
        assert index_redirect.layer == "middleware"

        home_redirect = _routing_rule(db, match_type="path_exact", match_value="/home")
        assert home_redirect is not None, "/home → / redirect not seeded"
        assert home_redirect.target_slug == "/"
        assert home_redirect.redirect_code == 301
        assert home_redirect.layer == "middleware"

    def test_seed_redirects_are_idempotent(self, db):
        populate_cms()
        populate_cms()
        for match_value in ("/index", "/home"):
            count = (
                db.session.query(CmsRoutingRule)
                .filter_by(match_type="path_exact", match_value=match_value)
                .count()
            )
            assert count == 1, f"redirect '{match_value}' duplicated on re-seed"
