"""S117 §4.2 — a small, dependency-light minifier for prerender HTML.

Single responsibility: shrink the writer's emitted ``var/seo/*.html`` when the
operator turns on ``minify_prerender_output``. It is deliberately NOT a full
HTML/JS parser toolchain (no new pip deps): a tiny regex tokeniser that

  1. pulls out the "protected" blocks — ``<pre>``, ``<textarea>``, ``<style>``,
     ``<script>`` — so their contents are never treated as inter-tag markup;
  2. minifies the ``<style>`` body (drop CSS comments, collapse whitespace) and
     the executable ``<script>`` body (CONSERVATIVE dedent + blank-line drop,
     never token rewrites);
  3. byte-preserves DATA scripts (``application/ld+json`` and the
     ``application/json`` ``__POST__`` payload) — those are content, not code;
  4. collapses insignificant inter-tag whitespace in the remaining markup
     (whitespace fully bounded by tags), leaving text-adjacent whitespace intact.

When the flag is off the writer never builds one, so the emitted document is
byte-identical to today's pretty-printed output (Liskov-safe default).
"""
import re

# A protected block is a full ``<tag ...>…</tag>`` whose inner content must not
# be treated as markup. ``.*?`` stops at the first matching close tag — the same
# boundary the browser's HTML parser uses for raw-text elements.
_PROTECTED_BLOCK = re.compile(
    r"<(?P<tag>pre|textarea|script|style)\b[^>]*>.*?</(?P=tag)>",
    re.IGNORECASE | re.DOTALL,
)

# Split a single protected block into (open-tag, body, close-tag).
_OPEN_BODY_CLOSE = re.compile(r"^(<[^>]*>)(.*)(</[^>]*>)$", re.DOTALL)

# Extract a ``type="…"`` attribute value from an opening tag.
_TYPE_ATTR = re.compile(r"""type\s*=\s*["']([^"']*)["']""", re.IGNORECASE)

# CSS comment (non-greedy across newlines).
_CSS_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)

# The placeholder that stands in for an extracted protected block while the
# surrounding markup is whitespace-collapsed. ``\x00`` never occurs in HTML text.
_PLACEHOLDER = "\x00{index}\x00"
_PLACEHOLDER_TOKEN = r"\x00\d+\x00"

_PROTECTED_TAGS_KEEP_BODY = ("pre", "textarea")


class PrerenderMinifier:
    """Minify a prerender HTML document (see module docstring)."""

    def minify(self, html: str) -> str:
        """Return a whitespace-collapsed, inline-CSS/JS-minified copy of ``html``.

        Null-safe: an empty/falsy input is returned unchanged.
        """
        if not html:
            return html

        blocks: list = []

        def _stash(match: "re.Match") -> str:
            processed = self._process_block(match.group("tag").lower(), match.group(0))
            blocks.append(processed)
            return _PLACEHOLDER.format(index=len(blocks) - 1)

        stripped = _PROTECTED_BLOCK.sub(_stash, html)
        collapsed = self._collapse_intertag_whitespace(stripped)
        return re.sub(
            _PLACEHOLDER_TOKEN,
            lambda match: blocks[int(match.group(0).strip("\x00"))],
            collapsed,
        )

    # ── protected blocks ────────────────────────────────────────────────────

    def _process_block(self, tag: str, block: str) -> str:
        if tag in _PROTECTED_TAGS_KEEP_BODY:
            return block
        match = _OPEN_BODY_CLOSE.match(block)
        if match is None:  # pragma: no cover - defensive (regex guarantees shape)
            return block
        open_tag, body, close_tag = match.group(1), match.group(2), match.group(3)
        if tag == "style":
            return open_tag + self._minify_css(body) + close_tag
        # A DATA script (JSON) is content, not code — byte-preserve it whole.
        if self._is_data_script(open_tag):
            return block
        return open_tag + self._minify_js(body) + close_tag

    @staticmethod
    def _is_data_script(open_tag: str) -> bool:
        type_match = _TYPE_ATTR.search(open_tag)
        if type_match is None:
            return False
        return "json" in type_match.group(1).lower()

    # ── body minifiers ──────────────────────────────────────────────────────

    @staticmethod
    def _minify_css(css: str) -> str:
        css = _CSS_COMMENT.sub("", css)
        css = re.sub(r"\s+", " ", css)
        # Trim whitespace around the safe structural punctuation only.
        css = re.sub(r"\s*([{};])\s*", r"\1", css)
        return css.strip()

    @staticmethod
    def _minify_js(js: str) -> str:
        """Conservative, ASI-safe collapse: dedent lines + drop blank lines.

        Newlines between statements are preserved (never merged) so automatic
        semicolon insertion still behaves; per-line content is left byte-exact
        so string literals are never rewritten.
        """
        lines = (line.strip() for line in js.splitlines())
        return "\n".join(line for line in lines if line)

    # ── document whitespace ─────────────────────────────────────────────────

    @staticmethod
    def _collapse_intertag_whitespace(text: str) -> str:
        """Collapse whitespace fully bounded by tags / protected placeholders.

        ``>text <`` (text-adjacent) whitespace is significant and preserved.
        """
        text = re.sub(r">[ \t\r\n]+<", "><", text)
        text = re.sub(r">[ \t\r\n]+(\x00\d+\x00)", r">\1", text)
        text = re.sub(r"(\x00\d+\x00)[ \t\r\n]+<", r"\1<", text)
        text = re.sub(r"(\x00\d+\x00)[ \t\r\n]+(\x00\d+\x00)", r"\1\2", text)
        return text.strip()
