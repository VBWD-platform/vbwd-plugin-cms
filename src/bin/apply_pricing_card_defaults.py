#!/usr/bin/env python3
"""Apply the seeded pricing-card defaults non-destructively.

Deploy runs the destructive ``populate_cms.py`` seeders on NO instance (they
would overwrite operator content), so newly-seeded pricing-card styling never
reaches an existing database that way. This applier is the safe counterpart: it
runs on every deploy and fills in the pricing-card defaults ONLY where the
operator has not already set a value. It is strictly non-destructive and fully
idempotent — a second run reports "already-current" and writes nothing.

Two passes touch existing widgets:

* Pricing-card component pass (vue-component): EVERY widget whose
  ``config.component_name`` is a pricing-card component
  (``NativePricingPlans`` / ``TariffPlanCollection``) is styled. For each of
  ``theme`` and ``features`` the seeded default is written ONLY when the key is
  currently absent / ``None`` / empty (``""`` or ``[]``); ``highlight_slug`` is
  filled the same way but ONLY on ``root``-category widgets (the only category
  with a real ``pro`` plan). Any existing operator value is kept. ``heading``,
  ``subtitle``, ``cta_label``, ``highlight_badge`` and ``image_url`` are NEVER
  written. Matching on ``component_name`` (not slug) is deliberate: a prod demo
  widget uses the component name AS its slug (``TariffPlanCollection``), so
  slug-matching would miss it — component_name catches every instance.
* ``pricing-embed-demo`` (html): the live ``<script>`` tag is upgraded to carry
  ``data-theme``/``data-highlight``/``data-features`` ONLY when it still matches
  the previously-seeded original (no ``data-highlight`` / ``data-features``
  yet). If it already carries them it is left alone (already-current or
  operator-modified). The widget is never created here — that is
  ``populate_cms``'s job.

Usage (matches how deploy / seed invokes it):
    cd /app && PYTHONPATH=/app python plugins/cms/src/bin/apply_pricing_card_defaults.py
"""
from __future__ import annotations

import base64
import re
import sys
from pathlib import Path
from typing import Dict, FrozenSet, List, Optional, Tuple

_PROJECT_ROOT = Path(__file__).resolve().parents[5]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from plugins.cms.src.bin import populate_cms  # noqa: E402
from plugins.cms.src.models.cms_widget import CmsWidget  # noqa: E402
from plugins.cms.src.repositories.cms_widget_repository import (  # noqa: E402
    CmsWidgetRepository,
)

EMBED_GUIDE_SLUG = "pricing-embed-demo"

# Every vue-component widget whose config.component_name is one of these renders
# a pricing-card grid and shares the same default styling.
PRICING_CARD_COMPONENT_NAMES: FrozenSet[str] = frozenset(
    {"NativePricingPlans", "TariffPlanCollection"}
)

# ``highlight_slug`` is only seeded/filled on widgets pointing at this category —
# the only one with a real ``pro`` plan; forcing it elsewhere would highlight a
# non-existent plan.
ROOT_CATEGORY = "root"

_LIVE_EMBED_CONTAINER_ID = "embed-live-preview"
_SCRIPT_TAG_PATTERN = re.compile(r"<script\b[^>]*>.*?</script>", re.DOTALL)


def is_pricing_card_widget(config: Optional[Dict[str, object]]) -> bool:
    """True when this widget config renders a pricing-card component.

    Matched on ``component_name`` (not slug): a prod demo widget uses the
    component name AS its slug, which slug-matching would miss.
    """
    if not config:
        return False
    component_name = config.get("component_name")
    return (
        isinstance(component_name, str)
        and component_name in PRICING_CARD_COMPONENT_NAMES
    )


def defaults_for_config(config: Optional[Dict[str, object]]) -> Dict[str, object]:
    """The pricing-card defaults that apply to THIS widget config.

    ``theme`` and ``features`` are universal; ``highlight_slug`` is included only
    for ``root``-category widgets (the only category with a ``pro`` plan). Values
    come from ``populate_cms.NATIVE_PRICING_CONFIG`` so the applier can never
    drift from what the seeder writes.
    """
    seed = populate_cms.NATIVE_PRICING_CONFIG
    defaults: Dict[str, object] = {
        "theme": seed["theme"],
        "features": seed["features"],
    }
    if (config or {}).get("category") == ROOT_CATEGORY:
        defaults["highlight_slug"] = seed["highlight_slug"]
    return defaults


def _is_empty(value: object) -> bool:
    """A config value counts as "unset" when it is None or an empty str/list."""
    return value is None or value == "" or value == []


def decide_config_defaults(
    config: Optional[Dict[str, object]], defaults: Dict[str, object]
) -> Tuple[Dict[str, object], Dict[str, str]]:
    """Return (new_config, decisions) for a pricing-card widget config.

    ``new_config`` is a fresh dict: every key already present is preserved, and
    each default key is filled ONLY when its current value is empty. ``decisions``
    maps each default key to ``"filled"`` or ``"kept"`` for logging. Keys outside
    ``defaults`` are never inspected or altered.
    """
    result: Dict[str, object] = dict(config or {})
    decisions: Dict[str, str] = {}
    for key, default_value in defaults.items():
        if _is_empty(result.get(key)):
            result[key] = default_value
            decisions[key] = "filled"
        else:
            decisions[key] = "kept"
    return result, decisions


def find_live_embed_script_tag(html: str) -> Optional[str]:
    """Return the single unescaped live ``<script>`` tag, or None.

    The live tag is the one whose attributes target the on-page preview
    container (``data-container="embed-live-preview"``); the HTML-escaped
    ``&lt;script&gt;`` documentation samples in the same guide are not matched.
    """
    for match in _SCRIPT_TAG_PATTERN.finditer(html):
        tag = match.group(0)
        if _LIVE_EMBED_CONTAINER_ID in tag:
            return tag
    return None


# The up-to-date live tag the seeder now ships. The applier writes exactly this
# string, so a second run finds it already in place.
NEW_LIVE_EMBED_SCRIPT_TAG: Optional[str] = find_live_embed_script_tag(
    populate_cms.PRICING_EMBED_GUIDE_HTML
)


def decide_embed_update(html: str) -> Tuple[Optional[str], str]:
    """Return (new_html_or_None, status) for the embed-guide HTML.

    status is one of:
      * ``updated`` — live tag still matched the original (no data-highlight /
        data-features); new_html carries the upgraded tag.
      * ``already-current`` — live tag already equals the seeded new tag.
      * ``operator-modified`` — live tag carries the new attributes but differs
        from the seeded tag; left untouched.
      * ``no-live-script`` — no live tag found; nothing to do.
    """
    tag = find_live_embed_script_tag(html)
    if tag is None:
        return None, "no-live-script"
    if "data-highlight" in tag or "data-features" in tag:
        if tag == NEW_LIVE_EMBED_SCRIPT_TAG:
            return None, "already-current"
        return None, "operator-modified"
    if NEW_LIVE_EMBED_SCRIPT_TAG is None:
        return None, "no-live-script"
    return html.replace(tag, NEW_LIVE_EMBED_SCRIPT_TAG, 1), "updated"


def _decode_widget_html(content_json: Optional[Dict[str, object]]) -> Optional[str]:
    """Decode the base64 HTML the seeder stores under content_json['content']."""
    if not content_json:
        return None
    encoded = content_json.get("content")
    if not isinstance(encoded, str) or not encoded:
        return None
    return base64.b64decode(encoded).decode("utf-8")


def _encode_widget_html(html: str) -> str:
    return base64.b64encode(html.encode("utf-8")).decode("ascii")


def _find_pricing_card_widgets(session) -> List[CmsWidget]:
    """Every vue-component widget rendering a pricing-card component.

    A read query in a maintenance script (not test-data / schema) is fine; it
    enumerates ALL vue-component widgets so component-name matching catches every
    instance regardless of slug.
    """
    widgets = (
        session.query(CmsWidget).filter(CmsWidget.widget_type == "vue-component").all()
    )
    return [widget for widget in widgets if is_pricing_card_widget(widget.config)]


def _apply_component_configs(
    session, repository: CmsWidgetRepository, summary: Dict[str, object]
) -> None:
    per_widget: Dict[str, object] = {}
    for widget in _find_pricing_card_widgets(session):
        new_config, decisions = decide_config_defaults(
            widget.config, defaults_for_config(widget.config)
        )
        filled = [key for key, verdict in decisions.items() if verdict == "filled"]
        if filled:
            widget.config = new_config
            repository.save(widget)
            print(f"  ~ widget '{widget.slug}' — filled seeded defaults {filled}")
            status = "updated"
        else:
            print(f"  = widget '{widget.slug}' (already-current)")
            status = "already-current"
        per_widget[widget.slug] = {"status": status, "filled": filled}
    if not per_widget:
        print("  = no pricing-card widgets found — skipped")
    summary["components"] = per_widget


def _apply_embed_widget(
    repository: CmsWidgetRepository, summary: Dict[str, object]
) -> None:
    widget = repository.find_by_slug(EMBED_GUIDE_SLUG)
    if widget is None:
        print(
            f"  = widget '{EMBED_GUIDE_SLUG}' absent — skipped "
            "(creation is populate_cms's job)"
        )
        summary["embed"] = "absent"
        return

    html = _decode_widget_html(widget.content_json)
    if html is None:
        print(f"  = widget '{EMBED_GUIDE_SLUG}' has no HTML content — skipped")
        summary["embed"] = "no-content"
        return

    new_html, status = decide_embed_update(html)
    if status == "updated" and new_html is not None:
        widget.content_json = {
            **(widget.content_json or {}),
            "content": _encode_widget_html(new_html),
        }
        repository.save(widget)
        print(f"  ~ widget '{EMBED_GUIDE_SLUG}' (live script tag upgraded)")
    elif status == "operator-modified":
        print(f"  = widget '{EMBED_GUIDE_SLUG}' operator-modified — skipped")
    else:
        print(f"  = widget '{EMBED_GUIDE_SLUG}' ({status})")
    summary["embed"] = status


def apply_pricing_card_defaults(session) -> Dict[str, object]:
    """Fill the pricing-card defaults where unset; commit the session.

    Returns a small summary dict describing what was done for each widget. Safe
    to run repeatedly: only genuinely-empty values are written.
    """
    repository = CmsWidgetRepository(session)
    summary: Dict[str, object] = {}
    _apply_component_configs(session, repository, summary)
    _apply_embed_widget(repository, summary)
    session.commit()
    return summary


def main() -> None:
    from sqlalchemy.exc import SQLAlchemyError

    from vbwd.extensions import db

    try:
        summary = apply_pricing_card_defaults(db.session)
    except SQLAlchemyError as exc:
        # Deploy invokes this unconditionally; a fresh instance may not have the
        # cms tables/rows yet. Log and exit cleanly rather than fail the deploy.
        db.session.rollback()
        print(
            "  cms pricing-card widgets unavailable — skipped "
            f"({exc.__class__.__name__})"
        )
        return
    print(f"  Pricing-card defaults: {summary}")


if __name__ == "__main__":
    from vbwd.app import create_app

    with create_app().app_context():
        main()
