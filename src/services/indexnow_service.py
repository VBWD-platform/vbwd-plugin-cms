"""IndexNow submitter — instantly notify Bing/Yandex/Seznam of a changed URL.

IndexNow (https://www.indexnow.org) lets a site push a changed URL to
participating search engines instead of waiting to be crawled — the fix for the
"Discovered but not crawled" backlog. The submitter builds the absolute URL from
the configured ``public_base_url`` and POSTs the protocol payload
(``host`` / ``key`` / ``keyLocation`` / ``urlList``) to the configured endpoint
(default ``https://api.indexnow.org/indexnow``, which fans out to the
participating engines).

Best-effort by contract (per Bing guidance a failed notification must never
break the publish flow): ``submit`` returns ``None`` when the feature is a no-op
(no base URL / no key), ``True`` on a 2xx, and ``False`` on any transport error
or non-2xx — it never raises. The HTTP transport is injected (defaulting to
``requests.post``) so tests use a fake and never touch the network.
"""
import logging
from typing import Any, Callable, Optional
from urllib.parse import urlparse

import requests

logger = logging.getLogger(__name__)

_DEFAULT_TIMEOUT_SECONDS = 10

# The injected HTTP transport mirrors ``requests.post``'s call shape
# (url, *, json=…, timeout=…) and returns an object exposing ``status_code``.
HttpPostTransport = Callable[..., Any]


class IndexNowSubmitter:
    """POSTs a single changed URL to the IndexNow endpoint (streaming, per-change).

    Constructed per submission from live config (``public_base_url`` / key /
    endpoint). An empty ``public_base_url`` or key disables the submitter — it
    returns ``None`` with no HTTP call — which is the configured-off default.
    """

    def __init__(
        self,
        public_base_url: str,
        key: str,
        endpoint: str,
        http_transport: Optional[HttpPostTransport] = None,
        timeout_seconds: int = _DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._public_base_url = (public_base_url or "").rstrip("/")
        self._key = key or ""
        self._endpoint = endpoint or ""
        self._http_post = http_transport or requests.post
        self._timeout_seconds = timeout_seconds

    def submit(self, path_or_url: str) -> Optional[bool]:
        """Notify IndexNow of ``path_or_url``; ``None`` no-op, else 2xx→True.

        A relative path is resolved against ``public_base_url``; an already
        absolute ``http(s)://`` URL is submitted verbatim. Returns ``None`` when
        the submitter is disabled (no base URL / key / endpoint), ``True`` on a
        2xx response, and ``False`` on any error or non-2xx (logged) — never
        raising, so the caller's publish flow is unaffected.
        """
        if not self._public_base_url or not self._key or not self._endpoint:
            return None

        target_url = self._absolute_url(path_or_url)
        payload = {
            "host": urlparse(self._public_base_url).netloc,
            "key": self._key,
            "keyLocation": f"{self._public_base_url}/{self._key}.txt",
            "urlList": [target_url],
        }
        try:
            response = self._http_post(
                self._endpoint,
                json=payload,
                timeout=self._timeout_seconds,
            )
        except Exception as exc:  # best-effort: any failure ⇒ swallow + log
            logger.warning("[cms.indexnow] submit failed for '%s': %s", target_url, exc)
            return False

        status_code = getattr(response, "status_code", None)
        if status_code is not None and 200 <= status_code < 300:
            return True
        logger.warning(
            "[cms.indexnow] endpoint returned status %s for '%s'",
            status_code,
            target_url,
        )
        return False

    def _absolute_url(self, path_or_url: str) -> str:
        """Resolve a public path against the base, or pass an absolute URL through."""
        value = (path_or_url or "").strip()
        if value.startswith("http://") or value.startswith("https://"):
            return value
        return self._public_base_url + "/" + value.lstrip("/")
