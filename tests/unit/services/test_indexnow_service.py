"""IndexNow submitter — POST a changed URL to the IndexNow endpoint.

The submitter builds the absolute URL from the configured ``public_base_url``
and POSTs the IndexNow payload (``host``/``key``/``keyLocation``/``urlList``) to
the configured endpoint (default ``https://api.indexnow.org/indexnow`` which
fans out to Bing/Yandex/Seznam). Best-effort by contract: a missing base URL is
a no-op (``None``) and any transport failure is swallowed (``False``) so a failed
notification never breaks the publish flow. No real network — the HTTP transport
is injected as a fake.

Engineering requirements (binding, restated): TDD-first; SOLID/DI (transport is
injected); DRY; Liskov (best-effort never raises); clean code; no
overengineering. Guard: ``bin/pre-commit-check.sh --plugin cms --full``.
"""
import logging
from unittest.mock import MagicMock

from plugins.cms.src.services.indexnow_service import IndexNowSubmitter


def _ok_response(status_code=200):
    response = MagicMock()
    response.status_code = status_code
    return response


def test_submit_posts_correct_indexnow_payload():
    transport = MagicMock(return_value=_ok_response())
    submitter = IndexNowSubmitter(
        public_base_url="https://example.com/",
        key="abcdef0123456789",
        endpoint="https://api.indexnow.org/indexnow",
        http_transport=transport,
    )

    result = submitter.submit("/pricing")

    assert result is True
    transport.assert_called_once()
    assert transport.call_args[0][0] == "https://api.indexnow.org/indexnow"
    payload = transport.call_args[1]["json"]
    assert payload["host"] == "example.com"
    assert payload["key"] == "abcdef0123456789"
    assert payload["keyLocation"] == "https://example.com/abcdef0123456789.txt"
    assert payload["urlList"] == ["https://example.com/pricing"]


def test_submit_accepts_an_absolute_url_verbatim():
    transport = MagicMock(return_value=_ok_response())
    submitter = IndexNowSubmitter(
        public_base_url="https://example.com",
        key="abcdef0123456789",
        endpoint="https://api.indexnow.org/indexnow",
        http_transport=transport,
    )

    submitter.submit("https://example.com/blog/post-1")

    payload = transport.call_args[1]["json"]
    assert payload["urlList"] == ["https://example.com/blog/post-1"]


def test_submit_home_path_maps_to_root_url():
    transport = MagicMock(return_value=_ok_response())
    submitter = IndexNowSubmitter(
        public_base_url="https://example.com",
        key="abcdef0123456789",
        endpoint="https://api.indexnow.org/indexnow",
        http_transport=transport,
    )

    submitter.submit("/")

    payload = transport.call_args[1]["json"]
    assert payload["urlList"] == ["https://example.com/"]


def test_submit_none_when_no_public_base_url():
    transport = MagicMock(return_value=_ok_response())
    submitter = IndexNowSubmitter(
        public_base_url="",
        key="abcdef0123456789",
        endpoint="https://api.indexnow.org/indexnow",
        http_transport=transport,
    )

    assert submitter.submit("/pricing") is None
    transport.assert_not_called()


def test_submit_none_when_no_key():
    transport = MagicMock(return_value=_ok_response())
    submitter = IndexNowSubmitter(
        public_base_url="https://example.com",
        key="",
        endpoint="https://api.indexnow.org/indexnow",
        http_transport=transport,
    )

    assert submitter.submit("/pricing") is None
    transport.assert_not_called()


def test_submit_best_effort_swallows_http_error(caplog):
    transport = MagicMock(side_effect=RuntimeError("boom"))
    submitter = IndexNowSubmitter(
        public_base_url="https://example.com",
        key="abcdef0123456789",
        endpoint="https://api.indexnow.org/indexnow",
        http_transport=transport,
    )

    with caplog.at_level(logging.WARNING):
        result = submitter.submit("/pricing")

    assert result is False
    assert caplog.records


def test_submit_false_on_non_2xx(caplog):
    transport = MagicMock(return_value=_ok_response(status_code=403))
    submitter = IndexNowSubmitter(
        public_base_url="https://example.com",
        key="abcdef0123456789",
        endpoint="https://api.indexnow.org/indexnow",
        http_transport=transport,
    )

    with caplog.at_level(logging.WARNING):
        result = submitter.submit("/pricing")

    assert result is False
    assert caplog.records
