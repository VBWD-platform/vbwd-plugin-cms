"""ContactFormService — validates, sanitizes, and rate-limits contact form submissions.

Responsibilities:
  - Honeypot check (bots fill the hidden field; humans don't)
  - Per-(widget_slug, IP) rate limiting via Redis
  - Field-level validation (required fields, type checks)
  - Input sanitization (strip tags, limit length)
  - Build event payload for ``contact_form.received``

No DB access — the caller (route) fetches the widget config and passes it in.
"""
from __future__ import annotations

import html
import re
import logging
from typing import Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from src.utils.redis_client import RedisClient

logger = logging.getLogger(__name__)

_MAX_FIELD_LENGTH = 4000
_MAX_OPTION_LENGTH = 200
_STRIP_TAGS_RE = re.compile(r"<[^>]+>")
# Absolute ceiling even if admin sets a high value
_RATE_LIMIT_CAP = 200


class ContactFormError(Exception):
    """Base error for contact-form validation failures."""


class HoneypotError(ContactFormError):
    """Honeypot field was filled — likely a bot."""


class RateLimitError(ContactFormError):
    """Too many submissions from this IP for this widget."""


class ValidationError(ContactFormError):
    """Required field missing or value invalid."""


class ContactFormService:
    """Processes a raw form submission and returns a clean event payload."""

    def __init__(self, redis_client: "RedisClient") -> None:
        self._redis = redis_client

    # ── Public API ────────────────────────────────────────────────────────────

    def process_submission(
        self,
        *,
        config: dict[str, Any],
        form_data: dict[str, Any],
        remote_ip: str,
    ) -> dict[str, Any]:
        """Validate and sanitize a contact form submission.

        Args:
            config: Widget config dict (``cms_widget.config``).
            form_data: Raw JSON body from the request.
            remote_ip: Client IP address.

        Returns:
            Clean payload dict ready for ``contact_form.received`` event.

        Raises:
            HoneypotError: Honeypot field filled.
            RateLimitError: IP exceeded the configured rate limit.
            ValidationError: Required field missing or value too long.
        """
        widget_slug: str = str(form_data.get("widget_slug", ""))

        self._check_honeypot(form_data)
        self._check_rate_limit(widget_slug, remote_ip, config)

        fields_config: list[dict] = config.get("fields", [])
        submitted: dict[str, Any] = form_data.get("fields", {})
        cleaned_fields = self._validate_and_sanitize(fields_config, submitted)

        return {
            "widget_slug": widget_slug,
            "recipient_email": config.get("recipient_email", ""),
            "fields": cleaned_fields,
            "remote_ip": remote_ip,
        }

    # ── Honeypot ──────────────────────────────────────────────────────────────

    @staticmethod
    def _check_honeypot(form_data: dict[str, Any]) -> None:
        """Raise HoneypotError if the hidden honeypot field is not empty."""
        value = form_data.get("_hp", "")
        if value:
            logger.info("[contact_form] Honeypot triggered from data=%s", form_data.get("widget_slug"))
            raise HoneypotError("Honeypot field filled")

    # ── Rate limiting ─────────────────────────────────────────────────────────

    def _check_rate_limit(
        self,
        widget_slug: str,
        remote_ip: str,
        config: dict[str, Any],
    ) -> None:
        """Enforce per-(widget, IP) rate limit using Redis INCR + EXPIRE.

        Config keys used:
            rate_limit_enabled (bool, default True)
            rate_limit_max     (int,  default 5)
            rate_limit_window_minutes (int, default 60)
        """
        if not config.get("rate_limit_enabled", True):
            return

        max_requests = min(
            int(config.get("rate_limit_max", 5)),
            _RATE_LIMIT_CAP,
        )
        window_seconds = int(config.get("rate_limit_window_minutes", 60)) * 60

        key = f"cf_rl:{widget_slug}:{remote_ip}"
        try:
            pipe = self._redis.client.pipeline()
            pipe.incr(key)
            pipe.expire(key, window_seconds)
            count, _ = pipe.execute()
            if count > max_requests:
                logger.warning(
                    "[contact_form] Rate limit hit: widget=%s ip=%s count=%d max=%d",
                    widget_slug, remote_ip, count, max_requests,
                )
                raise RateLimitError(f"Rate limit exceeded ({count}/{max_requests})")
        except RateLimitError:
            raise
        except Exception as exc:
            # Redis unavailable — fail open (don't block the user, just log)
            logger.error("[contact_form] Redis rate-limit check failed: %s", exc)

    # ── Field validation & sanitization ───────────────────────────────────────

    def _validate_and_sanitize(
        self,
        fields_config: list[dict],
        submitted: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Return a list of {id, label, value} dicts after validation & sanitization.

        Raises:
            ValidationError: If a required field is empty.
        """
        result: list[dict[str, Any]] = []

        for field in fields_config:
            field_id: str = field.get("id", "")
            label: str = field.get("label", field_id)
            required: bool = field.get("required", False)
            field_type: str = field.get("type", "text")
            raw_value: Any = submitted.get(field_id)

            cleaned = self._sanitize_value(raw_value, field_type, field.get("options", []))

            if required and not cleaned:
                raise ValidationError(f"Field '{label}' is required")

            result.append({"id": field_id, "label": label, "value": cleaned})

        return result

    @staticmethod
    def _sanitize_value(
        raw: Any,
        field_type: str,
        options: Optional[list] = None,
    ) -> str:
        """Strip HTML tags, escape entities, enforce length, validate type."""
        if raw is None:
            return ""

        # Checkbox returns list; radio/text return string
        if isinstance(raw, list):
            # Validate each choice against declared options if available
            allowed = set(str(o) for o in (options or []))
            cleaned_items = []
            for item in raw:
                val = _STRIP_TAGS_RE.sub("", str(item)).strip()[:_MAX_OPTION_LENGTH]
                val = html.escape(val)
                if allowed and val not in allowed:
                    continue
                cleaned_items.append(val)
            return ", ".join(cleaned_items)

        value: str = str(raw)

        # Strip HTML tags first, then HTML-escape remaining content
        value = _STRIP_TAGS_RE.sub("", value).strip()
        value = html.escape(value)

        # Enforce max length
        value = value[:_MAX_FIELD_LENGTH]

        # Type-specific validation (reject clearly wrong formats)
        if field_type == "email":
            if value and not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", value):
                raise ValidationError(f"Invalid email address: {value!r}")
        elif field_type == "url":
            if value and not re.match(r"^https?://", value):
                raise ValidationError(f"URL must start with http:// or https://")
        elif field_type == "radio" and options:
            allowed = {html.escape(str(o)) for o in options}
            if value and value not in allowed:
                raise ValidationError(f"Invalid option: {value!r}")

        return value
