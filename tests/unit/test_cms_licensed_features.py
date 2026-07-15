"""Unit: the CMS plugin declares ``cms`` as its licensable feature (S135 demo).

Core stays agnostic — it never names ``cms``. The plugin declares the feature id
via ``BasePlugin.licensed_features`` so the core ``licensed_feature_registry``
can collect it (and the ``@requires_license(feature="cms")`` gate matches it).

Engineering requirements (binding, restated): TDD-first (this asserts the
contract the gate depends on); DevOps-first (pure, no DB); SOLID/DI/DRY (the
feature id lives in exactly one place); Liskov (the property honours the
``BasePlugin`` contract — a tuple of ids); clean code; no overengineering.
Quality guard: ``bin/pre-commit-check.sh --plugin cms --full``.
"""
from plugins.cms import CmsPlugin


def test_cms_plugin_declares_cms_licensed_feature():
    """The plugin gates on exactly the ``cms`` feature id."""
    assert CmsPlugin().licensed_features == ("cms",)


def test_licensed_features_is_a_tuple_of_strings():
    """The declaration honours the ``BasePlugin.licensed_features`` contract."""
    features = CmsPlugin().licensed_features
    assert isinstance(features, tuple)
    assert all(isinstance(feature, str) for feature in features)
