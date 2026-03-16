"""Unit tests for ContactFormService.

Tests cover:
  - Honeypot detection
  - Rate limiting (allowed, blocked, Redis failure -> fail open)
  - Required field validation
  - Input sanitization (HTML stripping, entity escaping, length cap)
  - Type validation (email, url, radio options)
  - Checkbox multi-value handling
  - Happy-path payload shape
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

from plugins.cms.src.services.contact_form_service import (
    ContactFormService,
    HoneypotError,
    RateLimitError,
    ValidationError,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_redis(*, count: int = 1) -> MagicMock:
    """Return a mock RedisClient whose pipeline().execute() returns (count, True)."""
    pipe = MagicMock()
    pipe.execute.return_value = (count, True)
    mock = MagicMock()
    mock.client.pipeline.return_value = pipe
    return mock


def _make_service(redis=None) -> ContactFormService:
    return ContactFormService(redis or _make_redis())


BASE_CONFIG = {
    "component_name": "ContactForm",
    "recipient_email": "info@example.com",
    "success_message": "Thank you!",
    "rate_limit_enabled": True,
    "rate_limit_max": 5,
    "rate_limit_window_minutes": 60,
    "fields": [
        {"id": "name",    "type": "text",     "label": "Name",    "required": True},
        {"id": "email",   "type": "email",    "label": "Email",   "required": True},
        {"id": "message", "type": "textarea", "label": "Message", "required": False},
    ],
}

BASE_DATA = {
    "widget_slug": "contact-widget",
    "_hp": "",
    "fields": {
        "name": "John",
        "email": "john@example.com",
        "message": "Hello there",
    },
}


# ── Honeypot tests ────────────────────────────────────────────────────────────

class TestHoneypot:
    def test_empty_honeypot_passes(self):
        svc = _make_service()
        result = svc.process_submission(config=BASE_CONFIG, form_data=BASE_DATA, remote_ip="1.2.3.4")
        assert result["widget_slug"] == "contact-widget"

    def test_filled_honeypot_raises(self):
        svc = _make_service()
        data = {**BASE_DATA, "_hp": "I am a bot"}
        with pytest.raises(HoneypotError):
            svc.process_submission(config=BASE_CONFIG, form_data=data, remote_ip="1.2.3.4")

    def test_whitespace_only_honeypot_raises(self):
        svc = _make_service()
        data = {**BASE_DATA, "_hp": "   "}
        with pytest.raises(HoneypotError):
            svc.process_submission(config=BASE_CONFIG, form_data=data, remote_ip="1.2.3.4")


# ── Rate limiting tests ───────────────────────────────────────────────────────

class TestRateLimit:
    def test_first_request_allowed(self):
        svc = _make_service(_make_redis(count=1))
        result = svc.process_submission(config=BASE_CONFIG, form_data=BASE_DATA, remote_ip="1.2.3.4")
        assert result is not None

    def test_at_limit_allowed(self):
        svc = _make_service(_make_redis(count=5))
        result = svc.process_submission(config=BASE_CONFIG, form_data=BASE_DATA, remote_ip="1.2.3.4")
        assert result is not None

    def test_over_limit_raises(self):
        svc = _make_service(_make_redis(count=6))
        with pytest.raises(RateLimitError):
            svc.process_submission(config=BASE_CONFIG, form_data=BASE_DATA, remote_ip="1.2.3.4")

    def test_rate_limit_disabled_ignores_count(self):
        cfg = {**BASE_CONFIG, "rate_limit_enabled": False}
        svc = _make_service(_make_redis(count=999))
        result = svc.process_submission(config=cfg, form_data=BASE_DATA, remote_ip="1.2.3.4")
        assert result is not None

    def test_redis_failure_fails_open(self):
        """If Redis is unavailable the form submission should still succeed."""
        mock_redis = MagicMock()
        mock_redis.client.pipeline.side_effect = Exception("Redis down")
        svc = _make_service(mock_redis)
        result = svc.process_submission(config=BASE_CONFIG, form_data=BASE_DATA, remote_ip="1.2.3.4")
        assert result is not None

    def test_cap_enforced(self):
        """rate_limit_max above _RATE_LIMIT_CAP (200) is capped."""
        from plugins.cms.src.services.contact_form_service import _RATE_LIMIT_CAP
        cfg = {**BASE_CONFIG, "rate_limit_max": 9999}
        svc = _make_service(_make_redis(count=_RATE_LIMIT_CAP + 1))
        with pytest.raises(RateLimitError):
            svc.process_submission(config=cfg, form_data=BASE_DATA, remote_ip="1.2.3.4")


# ── Required-field validation ─────────────────────────────────────────────────

class TestValidation:
    def test_missing_required_name_raises(self):
        svc = _make_service()
        data = {**BASE_DATA, "fields": {"name": "", "email": "x@x.com"}}
        with pytest.raises(ValidationError, match="Name"):
            svc.process_submission(config=BASE_CONFIG, form_data=data, remote_ip="1.2.3.4")

    def test_missing_required_email_raises(self):
        svc = _make_service()
        data = {**BASE_DATA, "fields": {"name": "Bob", "email": ""}}
        with pytest.raises(ValidationError, match="Email"):
            svc.process_submission(config=BASE_CONFIG, form_data=data, remote_ip="1.2.3.4")

    def test_optional_field_missing_is_ok(self):
        svc = _make_service()
        data = {**BASE_DATA, "fields": {"name": "Bob", "email": "b@b.com"}}
        result = svc.process_submission(config=BASE_CONFIG, form_data=data, remote_ip="1.2.3.4")
        assert result is not None

    def test_invalid_email_format_raises(self):
        svc = _make_service()
        data = {**BASE_DATA, "fields": {"name": "Bob", "email": "not-an-email"}}
        with pytest.raises(ValidationError, match="email"):
            svc.process_submission(config=BASE_CONFIG, form_data=data, remote_ip="1.2.3.4")

    def test_invalid_url_raises(self):
        cfg = {**BASE_CONFIG, "fields": [
            {"id": "name",  "type": "text",  "label": "Name",    "required": True},
            {"id": "email", "type": "email", "label": "Email",   "required": True},
            {"id": "site",  "type": "url",   "label": "Website", "required": False},
        ]}
        svc = _make_service()
        data = {**BASE_DATA, "fields": {"name": "Bob", "email": "b@b.com", "site": "ftp://bad"}}
        with pytest.raises(ValidationError, match="http"):
            svc.process_submission(config=cfg, form_data=data, remote_ip="1.2.3.4")

    def test_valid_url_passes(self):
        cfg = {**BASE_CONFIG, "fields": [
            {"id": "name",  "type": "text",  "label": "Name",    "required": True},
            {"id": "email", "type": "email", "label": "Email",   "required": True},
            {"id": "site",  "type": "url",   "label": "Website", "required": False},
        ]}
        svc = _make_service()
        data = {**BASE_DATA, "fields": {"name": "Bob", "email": "b@b.com", "site": "https://example.com"}}
        result = svc.process_submission(config=cfg, form_data=data, remote_ip="1.2.3.4")
        assert result is not None


# ── Sanitization tests ────────────────────────────────────────────────────────

class TestSanitization:
    def test_html_tags_stripped(self):
        svc = _make_service()
        data = {**BASE_DATA, "fields": {"name": "<b>Alice</b>", "email": "a@a.com"}}
        result = svc.process_submission(config=BASE_CONFIG, form_data=data, remote_ip="1.2.3.4")
        name_field = next(f for f in result["fields"] if f["id"] == "name")
        assert "<b>" not in name_field["value"]
        assert "Alice" in name_field["value"]

    def test_script_tag_stripped(self):
        svc = _make_service()
        data = {**BASE_DATA, "fields": {
            "name": '<script>alert("xss")</script>Normal',
            "email": "a@a.com",
        }}
        result = svc.process_submission(config=BASE_CONFIG, form_data=data, remote_ip="1.2.3.4")
        name_field = next(f for f in result["fields"] if f["id"] == "name")
        assert "<script>" not in name_field["value"]
        assert "Normal" in name_field["value"]

    def test_entities_escaped(self):
        svc = _make_service()
        data = {**BASE_DATA, "fields": {"name": "A & B", "email": "a@a.com"}}
        result = svc.process_submission(config=BASE_CONFIG, form_data=data, remote_ip="1.2.3.4")
        name_field = next(f for f in result["fields"] if f["id"] == "name")
        assert "&amp;" in name_field["value"]

    def test_value_truncated_to_max_length(self):
        from plugins.cms.src.services.contact_form_service import _MAX_FIELD_LENGTH
        svc = _make_service()
        long_value = "A" * (_MAX_FIELD_LENGTH + 500)
        data = {**BASE_DATA, "fields": {"name": "Bob", "email": "b@b.com", "message": long_value}}
        result = svc.process_submission(config=BASE_CONFIG, form_data=data, remote_ip="1.2.3.4")
        msg_field = next(f for f in result["fields"] if f["id"] == "message")
        assert len(msg_field["value"]) <= _MAX_FIELD_LENGTH


# ── Radio / checkbox tests ────────────────────────────────────────────────────

class TestFieldTypes:
    def test_radio_valid_option(self):
        cfg = {**BASE_CONFIG, "fields": [
            {"id": "name",  "type": "text",  "label": "Name",  "required": True},
            {"id": "email", "type": "email", "label": "Email", "required": True},
            {"id": "topic", "type": "radio", "label": "Topic", "required": False,
             "options": ["General", "Support", "Sales"]},
        ]}
        svc = _make_service()
        data = {**BASE_DATA, "fields": {"name": "Bob", "email": "b@b.com", "topic": "Support"}}
        result = svc.process_submission(config=cfg, form_data=data, remote_ip="1.2.3.4")
        topic = next(f for f in result["fields"] if f["id"] == "topic")
        assert topic["value"] == "Support"

    def test_radio_invalid_option_raises(self):
        cfg = {**BASE_CONFIG, "fields": [
            {"id": "name",  "type": "text",  "label": "Name",  "required": True},
            {"id": "email", "type": "email", "label": "Email", "required": True},
            {"id": "topic", "type": "radio", "label": "Topic", "required": True,
             "options": ["General", "Support"]},
        ]}
        svc = _make_service()
        data = {**BASE_DATA, "fields": {"name": "Bob", "email": "b@b.com", "topic": "Hacked"}}
        with pytest.raises(ValidationError, match="Invalid option"):
            svc.process_submission(config=cfg, form_data=data, remote_ip="1.2.3.4")

    def test_checkbox_multiple_values_joined(self):
        cfg = {**BASE_CONFIG, "fields": [
            {"id": "name",     "type": "text",     "label": "Name",     "required": True},
            {"id": "email",    "type": "email",    "label": "Email",    "required": True},
            {"id": "services", "type": "checkbox", "label": "Services", "required": False,
             "options": ["Design", "Dev", "Consulting"]},
        ]}
        svc = _make_service()
        data = {**BASE_DATA, "fields": {
            "name": "Bob", "email": "b@b.com", "services": ["Design", "Dev"],
        }}
        result = svc.process_submission(config=cfg, form_data=data, remote_ip="1.2.3.4")
        services = next(f for f in result["fields"] if f["id"] == "services")
        assert "Design" in services["value"]
        assert "Dev" in services["value"]

    def test_checkbox_invalid_option_filtered(self):
        cfg = {**BASE_CONFIG, "fields": [
            {"id": "name",     "type": "text",     "label": "Name",     "required": True},
            {"id": "email",    "type": "email",    "label": "Email",    "required": True},
            {"id": "services", "type": "checkbox", "label": "Services", "required": False,
             "options": ["Design", "Dev"]},
        ]}
        svc = _make_service()
        data = {**BASE_DATA, "fields": {
            "name": "Bob", "email": "b@b.com",
            "services": ["Design", "INJECTED_VALUE"],
        }}
        result = svc.process_submission(config=cfg, form_data=data, remote_ip="1.2.3.4")
        services = next(f for f in result["fields"] if f["id"] == "services")
        assert "INJECTED_VALUE" not in services["value"]
        assert "Design" in services["value"]


# ── Payload shape test ────────────────────────────────────────────────────────

class TestPayloadShape:
    def test_payload_contains_expected_keys(self):
        svc = _make_service()
        result = svc.process_submission(config=BASE_CONFIG, form_data=BASE_DATA, remote_ip="10.0.0.1")
        assert result["widget_slug"] == "contact-widget"
        assert result["recipient_email"] == "info@example.com"
        assert result["remote_ip"] == "10.0.0.1"
        assert isinstance(result["fields"], list)
        assert len(result["fields"]) == 3

    def test_field_dicts_have_id_label_value(self):
        svc = _make_service()
        result = svc.process_submission(config=BASE_CONFIG, form_data=BASE_DATA, remote_ip="1.2.3.4")
        for f in result["fields"]:
            assert "id" in f
            assert "label" in f
            assert "value" in f
