"""Curated CMS editor-language catalog + enabled-language resolver.

The post/page editor and the content-list language filter offer a configurable
set of languages, driven by the CMS plugin's ``enabled_languages`` config value
(managed via the fe-admin "Languages" settings tab). This module owns the single
source of truth for the available catalog and the logic that resolves the
configured subset — tolerating BOTH a list value (``["en", "de"]``) and a legacy
CSV string (``"en,de"``), dropping unknown codes, preserving the configured
order, and falling back to English/German/Russian when nothing is configured.

Engineering requirements (binding, restated): TDD-first; DevOps-first; SOLID/
DI/DRY; Liskov; clean code; no overengineering.
"""
from typing import Dict, List

# Curated catalog of languages offered in the CMS editor. ``code`` is the
# ISO 639-1 code; ``label`` is the language's native name.
LANGUAGE_CATALOG: List[Dict[str, str]] = [
    {"code": "en", "label": "English"},
    {"code": "de", "label": "Deutsch"},
    {"code": "ru", "label": "Русский"},
    {"code": "fr", "label": "Français"},
    {"code": "es", "label": "Español"},
    {"code": "it", "label": "Italiano"},
    {"code": "pt", "label": "Português"},
    {"code": "nl", "label": "Nederlands"},
    {"code": "pl", "label": "Polski"},
    {"code": "uk", "label": "Українська"},
    {"code": "zh", "label": "中文"},
    {"code": "ja", "label": "日本語"},
    {"code": "ko", "label": "한국어"},
    {"code": "th", "label": "ไทย"},
    {"code": "ar", "label": "العربية"},
    {"code": "hi", "label": "हिन्दी"},
    {"code": "tr", "label": "Türkçe"},
    {"code": "cs", "label": "Čeština"},
    {"code": "sv", "label": "Svenska"},
    {"code": "fi", "label": "Suomi"},
]

# Labels keyed by code for O(1) lookup during resolution.
_LABELS_BY_CODE: Dict[str, str] = {
    entry["code"]: entry["label"] for entry in LANGUAGE_CATALOG
}

# Applied when ``enabled_languages`` is empty, missing, or contains no known code.
_DEFAULT_LANGUAGE_CODES: List[str] = ["en", "de", "ru"]


def _coerce_to_codes(value: object) -> List[str]:
    """Normalise a raw ``enabled_languages`` value into a list of code strings.

    Accepts a list (stored by the dual-list field) or a legacy CSV string, and
    trims surrounding whitespace on every code.
    """
    if isinstance(value, str):
        parts: List[object] = list(value.split(","))
    elif isinstance(value, list):
        parts = list(value)
    else:
        parts = []
    return [str(part).strip() for part in parts if str(part).strip()]


def resolve_enabled_languages(
    config_dict: Dict[str, object],
) -> List[Dict[str, str]]:
    """Resolve the configured enabled languages to catalog entries with labels.

    Reads ``enabled_languages`` from ``config_dict``, keeps only codes present in
    the catalog, preserves the configured order, and falls back to
    English/German/Russian when the resolved list would be empty.
    """
    requested_codes = _coerce_to_codes(config_dict.get("enabled_languages"))
    resolved = [
        {"code": code, "label": _LABELS_BY_CODE[code]}
        for code in requested_codes
        if code in _LABELS_BY_CODE
    ]
    if resolved:
        return resolved
    return [
        {"code": code, "label": _LABELS_BY_CODE[code]}
        for code in _DEFAULT_LANGUAGE_CODES
    ]
