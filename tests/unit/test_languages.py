"""Unit: curated language catalog + ``resolve_enabled_languages`` resolver.

The CMS editor-language list is configurable via the plugin's ``enabled_languages``
config value (managed by the fe-admin "Languages" tab). This suite pins the
catalog contract and the resolver's tolerance for BOTH a list value and a legacy
CSV string, order preservation, unknown-code dropping, and the en/de/ru fallback.

Engineering requirements (binding, restated): TDD-first; DevOps-first; SOLID/
DI/DRY; Liskov; clean code; no overengineering. Quality guard:
``bin/pre-commit-check.sh --plugin cms --full``.
"""
from plugins.cms.src.languages import (
    LANGUAGE_CATALOG,
    resolve_enabled_languages,
)


def _codes(languages):
    return [language["code"] for language in languages]


def test_catalog_has_expected_size_and_shape():
    assert len(LANGUAGE_CATALOG) == 20
    for entry in LANGUAGE_CATALOG:
        assert set(entry.keys()) == {"code", "label"}
        assert entry["code"]
        assert entry["label"]


def test_catalog_contains_curated_codes_with_native_labels():
    by_code = {entry["code"]: entry["label"] for entry in LANGUAGE_CATALOG}
    assert by_code["en"] == "English"
    assert by_code["de"] == "Deutsch"
    assert by_code["ru"] == "Русский"
    assert by_code["fr"] == "Français"
    assert by_code["uk"] == "Українська"
    assert by_code["zh"] == "中文"
    assert by_code["ar"] == "العربية"


def test_resolve_from_list_value_preserves_order():
    resolved = resolve_enabled_languages({"enabled_languages": ["de", "en", "fr"]})
    assert _codes(resolved) == ["de", "en", "fr"]
    assert resolved[0]["label"] == "Deutsch"


def test_resolve_from_csv_string_value():
    resolved = resolve_enabled_languages({"enabled_languages": "en,fr,ja"})
    assert _codes(resolved) == ["en", "fr", "ja"]


def test_resolve_drops_unknown_codes():
    resolved = resolve_enabled_languages({"enabled_languages": ["en", "xx", "fr"]})
    assert _codes(resolved) == ["en", "fr"]


def test_resolve_empty_value_falls_back_to_en_de_ru():
    assert _codes(resolve_enabled_languages({"enabled_languages": ""})) == [
        "en",
        "de",
        "ru",
    ]
    assert _codes(resolve_enabled_languages({"enabled_languages": []})) == [
        "en",
        "de",
        "ru",
    ]


def test_resolve_missing_key_falls_back_to_en_de_ru():
    assert _codes(resolve_enabled_languages({})) == ["en", "de", "ru"]


def test_resolve_all_unknown_falls_back_to_en_de_ru():
    assert _codes(resolve_enabled_languages({"enabled_languages": "xx,yy"})) == [
        "en",
        "de",
        "ru",
    ]


def test_resolve_trims_whitespace_in_csv():
    resolved = resolve_enabled_languages({"enabled_languages": " en , de "})
    assert _codes(resolved) == ["en", "de"]
