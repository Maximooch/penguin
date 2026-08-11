"""Small presentation helpers shared by the Telegram manager."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Mapping

if TYPE_CHECKING:
    from penguin.channels.schema import ChannelAddress


def delivery_payload(
    address: ChannelAddress,
    text: str,
    *,
    reply_to_message_id: str | None = None,
    edit_message_id: str | None = None,
) -> dict[str, Any]:
    return {
        "chat_id": address.chat_id,
        "topic_id": address.topic_id,
        "text": text,
        "reply_to_message_id": reply_to_message_id,
        "edit_message_id": edit_message_id,
    }


def value(item: Any, key: str) -> Any:
    if isinstance(item, Mapping):
        return item.get(key)
    return getattr(item, key, None)


def message_id(message: Any) -> str | None:
    identifier = value(message, "message_id")
    return str(identifier) if identifier is not None else None


def interactive_terminal_label(request: Any) -> str | None:
    status = getattr(getattr(request, "status", None), "value", "")
    return {
        "answered": "Answered",
        "rejected": "Denied",
        "approved": "Approved",
        "denied": "Denied",
        "expired": "Expired",
    }.get(str(status).casefold())


def inline_markup(raw: Any) -> Any:
    if not isinstance(raw, list) or not raw:
        return None
    try:
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    except ImportError:
        return raw
    rows = []
    for raw_row in raw:
        if not isinstance(raw_row, list):
            continue
        row = []
        for item in raw_row:
            if isinstance(item, Mapping) and item.get("text") and item.get("data"):
                row.append(
                    InlineKeyboardButton(
                        text=str(item["text"]), callback_data=str(item["data"])
                    )
                )
        if row:
            rows.append(row)
    return InlineKeyboardMarkup(rows) if rows else None
