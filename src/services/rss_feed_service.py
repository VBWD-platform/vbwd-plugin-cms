"""RssFeedService — standards-compliant RSS 2.0 for the blog / per-term archives.

The feed reuses the SAME post query as the public lists (S47.0/47.4): it asks
``PostService`` for published-only, newest-first, capped summaries and never
re-implements "fetch published posts" (DRY). The document is built with a real
XML serializer (``xml.etree.ElementTree``) so every value is escaped — no string
concatenation.

Item permalinks come from the post's ``canonical_url`` (the same absolute URL
the S47.1 SEO canonical / sitemap ``loc`` uses); when a post has no canonical
URL the feed falls back to ``<public_base_url>/<slug>``. The channel ``link`` is
the configured public base URL.
"""
from email.utils import format_datetime
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from xml.etree import ElementTree

from plugins.cms.src.models.cms_post import POST_STATUS_PUBLISHED

RSS_VERSION = "2.0"
DEFAULT_ITEM_LIMIT = 20
DEFAULT_LANGUAGE = "en"
DEFAULT_CHANNEL_TITLE = "Blog"
DEFAULT_CHANNEL_DESCRIPTION = ""


class RssFeedService:
    """Builds an RSS 2.0 document from the shared published-post query."""

    def __init__(
        self,
        post_service,
        *,
        public_base_url: str,
        item_limit: int = DEFAULT_ITEM_LIMIT,
        channel_title: str = DEFAULT_CHANNEL_TITLE,
        channel_description: str = DEFAULT_CHANNEL_DESCRIPTION,
        language: str = DEFAULT_LANGUAGE,
    ) -> None:
        self._post_service = post_service
        self._public_base_url = (public_base_url or "").rstrip("/")
        self._item_limit = (
            item_limit if item_limit and item_limit > 0 else (DEFAULT_ITEM_LIMIT)
        )
        self._channel_title = channel_title
        self._channel_description = channel_description
        self._language = language

    def build(
        self,
        *,
        post_type: Optional[str] = "post",
        term: Optional[Tuple[str, str]] = None,
    ) -> str:
        """Return the RSS 2.0 XML for the blog or a per-term archive.

        ``post_type`` filters by content type (default ``post``); ``term`` is an
        optional ``(term_type, term_slug)`` pair narrowing to one taxonomy term.
        An unknown term simply yields an empty (but valid) channel.
        """
        items = self._published_summaries(post_type=post_type, term=term)

        rss = ElementTree.Element("rss", attrib={"version": RSS_VERSION})
        channel = ElementTree.SubElement(rss, "channel")
        self._append_channel_header(channel)
        for summary in items:
            self._append_item(channel, summary)

        xml_bytes = ElementTree.tostring(rss, encoding="utf-8", xml_declaration=True)
        return xml_bytes.decode("utf-8")

    # ── post query (reused — never duplicated) ────────────────────────────

    def _published_summaries(
        self,
        *,
        post_type: Optional[str],
        term: Optional[Tuple[str, str]],
    ) -> List[Dict[str, Any]]:
        if term:
            term_type, term_slug = term
            page = self._post_service.list_posts_by_term(
                term_type=term_type,
                term_slug=term_slug,
                post_type=post_type,
                status=POST_STATUS_PUBLISHED,
                page=1,
                per_page=self._item_limit,
                newest_first=True,
            )
        else:
            page = self._post_service.list_posts(
                post_type=post_type,
                status=POST_STATUS_PUBLISHED,
                page=1,
                per_page=self._item_limit,
                newest_first=True,
            )
        return list(page.get("items", []))

    # ── XML assembly (escaped by the serializer) ──────────────────────────

    def _append_channel_header(self, channel: ElementTree.Element) -> None:
        self._text_child(channel, "title", self._channel_title)
        self._text_child(channel, "link", self._public_base_url)
        self._text_child(channel, "description", self._channel_description)
        self._text_child(channel, "language", self._language)
        self._text_child(
            channel,
            "lastBuildDate",
            format_datetime(datetime.now(timezone.utc)),
        )

    def _append_item(
        self, channel: ElementTree.Element, summary: Dict[str, Any]
    ) -> None:
        item = ElementTree.SubElement(channel, "item")
        link = self._item_link(summary)
        self._text_child(item, "title", summary.get("title") or "")
        self._text_child(item, "link", link)

        guid = ElementTree.SubElement(item, "guid", attrib={"isPermaLink": "true"})
        guid.text = link

        pub_date = self._rfc_822(summary.get("published_at"))
        if pub_date:
            self._text_child(item, "pubDate", pub_date)

        description = self._item_description(summary)
        if description:
            self._text_child(item, "description", description)

    def _item_link(self, summary: Dict[str, Any]) -> str:
        canonical_url = summary.get("canonical_url")
        if canonical_url:
            return canonical_url
        slug = (summary.get("slug") or "").lstrip("/")
        return f"{self._public_base_url}/{slug}"

    def _item_description(self, summary: Dict[str, Any]) -> str:
        excerpt = summary.get("excerpt")
        if excerpt:
            return excerpt
        meta_description = summary.get("meta_description")
        if meta_description:
            return meta_description
        return self._strip_html(summary.get("content_html") or "")

    def _rfc_822(self, published_at: Optional[str]) -> Optional[str]:
        if not published_at:
            return None
        moment = self._parse_iso(published_at)
        if moment is None:
            return None
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        return format_datetime(moment)

    @staticmethod
    def _parse_iso(value: str) -> Optional[datetime]:
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None

    @staticmethod
    def _strip_html(html: str) -> str:
        """Remove tags so the description carries plain text only.

        The serializer escapes the result; stripping tags keeps a sanitized,
        reader-friendly summary instead of leaking author markup.
        """
        import re

        text = re.sub(r"<[^>]+>", "", html)
        return " ".join(text.split())

    @staticmethod
    def _text_child(parent: ElementTree.Element, tag: str, text: str) -> None:
        child = ElementTree.SubElement(parent, tag)
        child.text = text
