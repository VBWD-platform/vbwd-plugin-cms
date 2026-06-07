"""cms contact-form → meinchat payload block (S60).

The ``/api/v1/contact`` route enriches the ``contact_form.received`` event
payload with a ``meinchat`` block read straight from the widget config so
the (optional) meinchat plugin can deliver the submission as a message.
cms knows nothing about meinchat beyond copying these config keys — no
repo coupling.
"""
from plugins.cms.src.routes import build_meinchat_payload_block


def test_block_carries_configured_settings():
    config = {
        "meinchat_enabled": True,
        "meinchat_sender_email": "form-bot@example.com",
        "meinchat_sender_nickname": "ContactBot",
        "meinchat_recipients": ["@admin", "@support"],
    }

    block = build_meinchat_payload_block(config)

    assert block == {
        "enabled": True,
        "sender_email": "form-bot@example.com",
        "sender_nickname": "ContactBot",
        "recipients": ["@admin", "@support"],
    }


def test_recipients_default_to_admin():
    config = {
        "meinchat_enabled": True,
        "meinchat_sender_email": "form-bot@example.com",
        "meinchat_sender_nickname": "ContactBot",
    }

    block = build_meinchat_payload_block(config)

    assert block["recipients"] == ["@admin"]


def test_disabled_when_flag_absent():
    block = build_meinchat_payload_block({})

    assert block["enabled"] is False
