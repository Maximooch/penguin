from __future__ import annotations

from hypothesis import given, strategies as st

from penguin.integrations.telegram.formatting import (
    StreamingCoalescer,
    formatted_chunks,
    html_chunks,
    plain_chunks,
    plain_text,
    render_html,
    split_text,
    utf16_length,
)


def test_utf16_split_respects_telegram_limit_without_losing_text() -> None:
    text = ("word 😀\n" * 700) + "done"
    chunks = split_text(text)

    assert "".join(chunks) == text
    assert len(chunks) > 1
    assert all(utf16_length(chunk) <= 4000 for chunk in chunks)
    assert utf16_length("😀") == 2


def test_render_html_escapes_input_and_formats_safe_markdown() -> None:
    text = (
        "# Heading\n**bold** and *italic* with <script>alert(1)</script> "
        "and [docs](https://example.com?a=1&b=2) and `x < y`"
    )

    rendered = render_html(text)

    assert rendered.startswith("<b>Heading</b>")
    assert "<b>bold</b>" in rendered
    assert "<i>italic</i>" in rendered
    assert "&lt;script&gt;" in rendered
    assert "<script>" not in rendered
    assert '<a href="https://example.com?a=1&amp;b=2">docs</a>' in rendered
    assert "<code>x &lt; y</code>" in rendered


def test_html_chunks_account_for_escape_expansion() -> None:
    chunks = html_chunks("<" * 5000)

    assert "".join(chunks) == "&lt;" * 5000
    assert all(utf16_length(chunk) <= 4000 for chunk in chunks)


def test_html_and_plain_fallback_chunks_stay_aligned() -> None:
    markdown = ("<unsafe> **bold** and `code`\n" * 1000) + "done"

    chunks = formatted_chunks(markdown)

    assert [html for html, _plain in chunks] == html_chunks(markdown)
    assert all(utf16_length(html) <= 4000 for html, _plain in chunks)
    assert all(utf16_length(plain) <= 4000 for _html, plain in chunks)
    assert len(chunks) > 1


def test_plain_fallback_removes_supported_markdown_and_splits() -> None:
    markdown = "# **Title**\nUse `code` and [docs](https://example.com)." * 200

    fallback = plain_text(markdown)
    chunks = plain_chunks(markdown, limit=200)

    assert "**" not in fallback
    assert "`" not in fallback
    assert "[docs]" not in fallback
    assert "".join(chunks) == fallback
    assert all(utf16_length(chunk) <= 200 for chunk in chunks)


def test_streaming_coalescer_throttles_cumulative_previews() -> None:
    coalescer = StreamingCoalescer(interval_seconds=0.75)

    coalescer.push("hel")
    assert coalescer.take(1.0) == "hel"
    coalescer.push("lo")
    assert coalescer.take(1.5) is None
    assert coalescer.take(1.75) == "hello"
    assert coalescer.take(2.0) is None
    coalescer.push("!")
    assert coalescer.take(2.1, force=True) == "hello!"


@given(
    st.text(
        alphabet=st.characters(blacklist_categories=("Cs",)),
        max_size=500,
    )
)
def test_arbitrary_unicode_chunks_never_exceed_telegram_limit(text: str) -> None:
    chunks = formatted_chunks(text, limit=64)

    assert all(utf16_length(html) <= 64 for html, _plain in chunks)
    assert all(utf16_length(plain) <= 64 for _html, plain in chunks)
    assert "".join(split_text(text, limit=64)) == text
