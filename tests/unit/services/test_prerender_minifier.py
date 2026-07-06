"""S117 T2 — ``PrerenderMinifier.minify`` (single-responsibility, dep-light).

The minifier shrinks the emitted ``var/seo/*.html`` when the operator turns on
``minify_prerender_output``:

  * the inline ``<style data-seo="ssr-style">`` body is CSS-minified;
  * executable inline ``<script>`` bodies get a CONSERVATIVE whitespace collapse
    (dedent + blank-line drop) — never token rewrites;
  * ``<script type="application/ld+json">`` and the
    ``<script type="application/json" id="__POST__">`` payload are byte-preserved
    (they are DATA, not code);
  * insignificant inter-tag whitespace is collapsed, but the contents of
    ``<pre>``/``<textarea>``/``<script>``/``<style>`` are preserved.

Engineering requirements (binding, restated): TDD-first; DevOps-first; SOLID
(single responsibility); DI (the writer receives one lazily); DRY; Liskov (flag
off ⇒ baseline unchanged); clean code; no overengineering (a small regex
tokeniser, no HTML/JS parser toolchain). Guard:
``bin/pre-commit-check.sh --plugin cms --full``.
"""
import json

from plugins.cms.src.services.prerender_minifier import PrerenderMinifier


def _minifier() -> PrerenderMinifier:
    return PrerenderMinifier()


def test_minifies_inline_ssr_style_block():
    html = (
        "<html><head>"
        '<style data-seo="ssr-style">\n'
        "  /* brand colours */\n"
        "  .hero {\n"
        "      color: red;\n"
        "  }\n"
        "</style>"
        "</head><body></body></html>"
    )
    out = _minifier().minify(html)

    assert "/* brand colours */" not in out
    assert ".hero{" in out
    # The whole style body collapsed onto no indentation / newlines.
    assert "\n" not in out[out.index("<style") : out.index("</style>")]
    # The opening tag (with its marker attribute) is preserved verbatim.
    assert '<style data-seo="ssr-style">' in out


def test_minifies_inline_js_script_body():
    html = (
        "<html><head>"
        "<script>\n"
        "  function greet() {\n"
        '      console.log("hello world");\n'
        "  }\n"
        "\n"
        "  greet();\n"
        "</script>"
        "</head><body></body></html>"
    )
    out = _minifier().minify(html)

    body = out[out.index("<script>") + len("<script>") : out.index("</script>")]
    # Indentation + blank lines are gone ...
    assert "\n\n" not in body
    assert "\n  " not in body
    assert body.startswith("function greet()")
    # ... but the token/string content survives byte-exact (no rewrites).
    assert 'console.log("hello world");' in body


def test_leaves_ld_json_and_post_payload_untouched():
    ld = {"@context": "https://schema.org", "name": "Two  spaces  kept"}
    post = {"slug": "pricing", "title": "Pricing", "content_html": "<p>  keep  </p>"}
    ld_block = (
        '<script type="application/ld+json">'
        + json.dumps(ld, ensure_ascii=False)
        + "</script>"
    )
    post_block = (
        '<script type="application/json" id="__POST__">'
        + json.dumps(post, ensure_ascii=False)
        + "</script>"
    )
    html = f"<html><head>{ld_block}</head><body>{post_block}</body></html>"

    out = _minifier().minify(html)

    # Both data payloads survive byte-for-byte (spaces inside JSON untouched).
    assert ld_block in out
    assert post_block in out


def test_collapses_intertag_whitespace_but_preserves_pre_textarea():
    html = (
        "<html>\n"
        "  <body>\n"
        "    <div>\n"
        "      <span>hello</span>\n"
        "    </div>\n"
        "    <pre>\n  line one\n    line two\n</pre>\n"
        "    <textarea>\n  keep    me\n</textarea>\n"
        "  </body>\n"
        "</html>\n"
    )
    out = _minifier().minify(html)

    # Insignificant inter-tag whitespace collapsed.
    assert "<body><div>" in out
    assert "</div>" in out
    assert "</span></div>" in out
    # <pre>/<textarea> internal whitespace preserved verbatim.
    assert "<pre>\n  line one\n    line two\n</pre>" in out
    assert "<textarea>\n  keep    me\n</textarea>" in out


def test_empty_or_no_inline_blocks_is_noop():
    minifier = _minifier()
    assert minifier.minify("") == ""
    assert minifier.minify(None) is None
    # A doc already free of inline blocks and inter-tag whitespace is unchanged.
    already = '<html><head></head><body><div id="app"><p>x</p></div></body></html>'
    assert minifier.minify(already) == already


def test_text_adjacent_whitespace_is_preserved():
    # Whitespace between text and a tag is significant and must NOT be dropped.
    html = "<p>Hello <strong>world</strong> today</p>"
    out = _minifier().minify(html)
    assert out == html


def test_module_script_with_external_src_is_untouched():
    html = (
        "<head>"
        '<script type="module" src="/assets/index-deadbeef.js"></script>'
        "</head>"
    )
    out = _minifier().minify(html)
    assert '<script type="module" src="/assets/index-deadbeef.js"></script>' in out
