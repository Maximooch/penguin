"""Telegram approval presentation and terminal-delivery helpers."""

from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, Mapping

from penguin.integrations.telegram._helpers import message_id
from penguin.integrations.telegram.formatting import (
    TELEGRAM_TEXT_LIMIT,
    plain_text,
    render_html,
    utf16_length,
)

__all__ = ["approval_buttons", "send_terminal_edit", "terminal_edit_payload"]


def approval_buttons(callback_id: str, prefix: str) -> list[list[dict[str, str]]]:
    """Build bounded approval controls for one durable callback."""

    return [
        [
            {"text": "Approve once", "data": f"{prefix}{callback_id}:approve"},
            {
                "text": "Approve for session",
                "data": f"{prefix}{callback_id}:approve_session",
            },
        ],
        [{"text": "Deny", "data": f"{prefix}{callback_id}:deny"}],
    ]


def terminal_edit_payload(
    projection_payload: Mapping[str, Any],
    *,
    label: str,
    chat_id: Any,
    message_id: str,
) -> tuple[dict[str, Any], str]:
    """Preserve an interactive prompt while removing its active controls."""

    original = str(projection_payload.get("text") or "")
    text, fallback = _fit_terminal_text(original, label)
    return (
        {
            "chat_id": chat_id,
            "message_id": int(message_id),
            "text": text,
            "parse_mode": "HTML",
            "reply_markup": None,
        },
        fallback,
    )


def _fit_terminal_text(original: str, label: str) -> tuple[str, str]:
    """Fit the prompt prefix and terminal marker into one Telegram message."""

    suffix = f"\n\n**{label}**"

    def render(prefix_end: int) -> tuple[str, str]:
        source = f"{original[:prefix_end]}{suffix}"
        return render_html(source), plain_text(source)

    text, fallback = render(len(original))
    if max(utf16_length(text), utf16_length(fallback)) <= TELEGRAM_TEXT_LIMIT:
        return text, fallback

    lower = 0
    upper = len(original)
    best = render(0)
    if max(utf16_length(best[0]), utf16_length(best[1])) > TELEGRAM_TEXT_LIMIT:
        raise ValueError("terminal approval marker exceeds Telegram's text limit")

    while lower <= upper:
        midpoint = (lower + upper) // 2
        candidate = render(midpoint)
        if (
            max(utf16_length(candidate[0]), utf16_length(candidate[1]))
            <= TELEGRAM_TEXT_LIMIT
        ):
            best = candidate
            lower = midpoint + 1
        else:
            upper = midpoint - 1
    return best


async def send_terminal_edit(
    *,
    store: Any,
    bot: Any,
    api_call: Callable[[Any], Awaitable[Any]],
    account_id: str,
    payload: Mapping[str, Any],
    chat_id: Any,
) -> str | None:
    """Replace an already-delivered approval prompt with its terminal state."""

    projection = await asyncio.to_thread(
        store.get_delivery,
        str(payload.get("projection_delivery_id") or ""),
        platform="telegram",
        account_id=account_id,
    )
    if projection is None or not projection.external_message_id:
        return None
    kwargs, fallback = terminal_edit_payload(
        projection.payload,
        label=str(payload.get("label") or "Expired"),
        chat_id=chat_id,
        message_id=projection.external_message_id,
    )
    try:
        response = await api_call(bot.edit_message_text(**kwargs))
    except Exception as exc:
        if type(exc).__name__ != "BadRequest":
            raise
        kwargs.update(text=fallback, parse_mode=None)
        response = await api_call(bot.edit_message_text(**kwargs))
    return message_id(response) or projection.external_message_id
