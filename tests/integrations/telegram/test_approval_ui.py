"""Focused tests for Telegram approval presentation helpers."""

from penguin.integrations.telegram._approval_ui import terminal_edit_payload
from penguin.integrations.telegram.formatting import (
    TELEGRAM_TEXT_LIMIT,
    utf16_length,
)


def test_terminal_edit_keeps_exact_boundary_prompt_and_marker() -> None:
    marker = "\n\n<b>Approved</b>"
    original = "a" * (TELEGRAM_TEXT_LIMIT - utf16_length(marker))

    payload, fallback = terminal_edit_payload(
        {"text": original},
        label="Approved",
        chat_id="42",
        message_id="7",
    )

    assert payload["text"] == f"{original}{marker}"
    assert utf16_length(payload["text"]) == TELEGRAM_TEXT_LIMIT
    assert fallback.endswith("\n\nApproved")


def test_terminal_edit_truncates_emoji_prompt_but_keeps_expired_marker() -> None:
    original = "🐧" * 3_000
    marker = "\n\n<b>Expired</b>"

    payload, fallback = terminal_edit_payload(
        {"text": original},
        label="Expired",
        chat_id="42",
        message_id="7",
    )

    expected_penguins = (TELEGRAM_TEXT_LIMIT - utf16_length(marker)) // 2
    assert payload["text"] == f"{'🐧' * expected_penguins}{marker}"
    assert fallback.endswith("\n\nExpired")
    assert utf16_length(payload["text"]) <= TELEGRAM_TEXT_LIMIT
    assert utf16_length(fallback) <= TELEGRAM_TEXT_LIMIT
