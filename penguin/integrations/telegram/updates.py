"""Pure normalization for Telegram Bot API updates."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Mapping

from penguin.channels.schema import Attachment, ChannelAddress, InboundEnvelope

__all__ = [
    "envelope_from_dict",
    "envelope_to_dict",
    "is_addressed_to_bot",
    "normalize_update",
    "parse_command",
    "strip_bot_mention",
    "update_to_dict",
]


def update_to_dict(update: Any) -> dict[str, Any]:
    """Return a plain update dictionary without retaining PTB objects."""

    if isinstance(update, Mapping):
        return dict(update)
    converter = getattr(update, "to_dict", None)
    if callable(converter):
        converted = converter()
        if isinstance(converted, Mapping):
            return dict(converted)
    raise TypeError("Telegram update must be a mapping or expose to_dict()")


def normalize_update(update: Any, *, account_id: str) -> InboundEnvelope | None:
    """Normalize a message or callback update into the channel contract."""

    raw = update_to_dict(update)
    update_id = _int(raw.get("update_id"))
    if update_id is None:
        return None

    callback = _mapping(raw.get("callback_query"))
    message = _mapping(callback.get("message")) if callback else {}
    if not message:
        message = _mapping(
            raw.get("message") or raw.get("edited_message") or raw.get("channel_post")
        )
    if not message:
        return None

    chat = _mapping(message.get("chat"))
    sender = _mapping(callback.get("from")) if callback else {}
    if not sender:
        sender = _mapping(message.get("from"))
    chat_id = _identifier(chat.get("id"))
    sender_id = _identifier(sender.get("id"))
    if not chat_id:
        return None

    topic_id = _identifier(message.get("message_thread_id"))
    text = str(message.get("text") or message.get("caption") or "")
    reply = _mapping(message.get("reply_to_message"))
    reply_sender = _mapping(reply.get("from"))
    callback_data = callback.get("data")
    callback_id = callback.get("id")

    metadata: dict[str, Any] = {
        "chat_type": str(chat.get("type") or "private"),
        "message_id": _identifier(message.get("message_id")),
        "chat_title": _bounded(chat.get("title"), 256),
        "callback_id": _bounded(callback_id, 256),
        "callback_data": _bounded(callback_data, 512),
        "reply_text": _bounded(reply.get("text") or reply.get("caption"), 2000),
        "reply_sender_id": _identifier(reply_sender.get("id")),
        "migrate_to_chat_id": _identifier(message.get("migrate_to_chat_id")),
        "migrate_from_chat_id": _identifier(message.get("migrate_from_chat_id")),
    }
    metadata = {
        key: value for key, value in metadata.items() if value not in (None, "")
    }
    is_migration = bool(
        metadata.get("migrate_to_chat_id") or metadata.get("migrate_from_chat_id")
    )
    if not sender_id and not is_migration:
        return None
    attachments = tuple(_attachments(message))
    if not (
        text
        or attachments
        or metadata.get("callback_data")
        or metadata.get("migrate_to_chat_id")
        or metadata.get("migrate_from_chat_id")
    ):
        return None

    return InboundEnvelope(
        event_id=f"telegram:{account_id}:{update_id}",
        source_sequence=update_id,
        address=ChannelAddress(
            platform="telegram",
            account_id=str(account_id),
            chat_id=chat_id,
            topic_id=topic_id,
        ),
        sender_id=sender_id or "",
        sender_username=_bounded(sender.get("username"), 64),
        text=text,
        reply_to_message_id=_identifier(reply.get("message_id")) or None,
        attachments=attachments,
        metadata=metadata,
    )


def parse_command(text: str) -> tuple[str | None, str, str | None]:
    """Return command name, arguments, and optional addressed bot username."""

    stripped = (text or "").strip()
    if not stripped.startswith("/"):
        return None, stripped, None
    head, _, arguments = stripped.partition(" ")
    command_and_target = head[1:].split("@", 1)
    command = command_and_target[0].strip().lower()
    target = command_and_target[1].strip() if len(command_and_target) == 2 else None
    if not command:
        return None, arguments.strip(), target
    return command, arguments.strip(), target


def is_addressed_to_bot(text: str, username: str) -> bool:
    """Return whether a command or mention is addressed to this bot."""

    command, _arguments, target = parse_command(text)
    if command is not None:
        return target is None or target.casefold() == username.lstrip("@").casefold()
    return f"@{username.lstrip('@')}".casefold() in (text or "").casefold()


def strip_bot_mention(text: str, username: str) -> str:
    """Remove this bot's explicit mention without altering other usernames."""

    mention = f"@{username.lstrip('@')}"
    source = text or ""
    index = source.casefold().find(mention.casefold())
    if index < 0:
        return source.strip()
    return (source[:index] + source[index + len(mention) :]).strip()


def envelope_to_dict(envelope: InboundEnvelope) -> dict[str, Any]:
    """Serialize an envelope for the durable ingress store."""

    return {
        "event_id": envelope.event_id,
        "source_sequence": envelope.source_sequence,
        "address": asdict(envelope.address),
        "sender_id": envelope.sender_id,
        "sender_username": envelope.sender_username,
        "text": envelope.text,
        "reply_to_message_id": envelope.reply_to_message_id,
        "attachments": [asdict(item) for item in envelope.attachments],
        "metadata": dict(envelope.metadata),
    }


def envelope_from_dict(payload: Mapping[str, Any]) -> InboundEnvelope:
    """Deserialize a validated store payload."""

    address = _mapping(payload.get("address"))
    attachments: list[Attachment] = []
    raw_attachments = payload.get("attachments")
    if isinstance(raw_attachments, list):
        for item in raw_attachments:
            data = _mapping(item)
            if data.get("kind") and data.get("file_id"):
                attachments.append(
                    Attachment(
                        kind=str(data["kind"]),
                        file_id=str(data["file_id"]),
                        file_name=_optional_string(data.get("file_name")),
                        mime_type=_optional_string(data.get("mime_type")),
                        size=_int(data.get("size")),
                    )
                )
    return InboundEnvelope(
        event_id=str(payload["event_id"]),
        source_sequence=int(payload["source_sequence"]),
        address=ChannelAddress(
            platform=str(address["platform"]),
            account_id=str(address["account_id"]),
            chat_id=str(address["chat_id"]),
            topic_id=str(address.get("topic_id") or ""),
        ),
        sender_id=str(payload["sender_id"]),
        sender_username=_optional_string(payload.get("sender_username")),
        text=str(payload.get("text") or ""),
        reply_to_message_id=_optional_string(payload.get("reply_to_message_id")),
        attachments=tuple(attachments),
        metadata=dict(_mapping(payload.get("metadata"))),
    )


def _attachments(message: Mapping[str, Any]) -> list[Attachment]:
    result: list[Attachment] = []
    photos = message.get("photo")
    if isinstance(photos, list) and photos:
        photo = max(
            (_mapping(item) for item in photos),
            key=lambda item: int(item.get("file_size") or 0),
        )
        if photo.get("file_id"):
            result.append(
                Attachment(
                    kind="photo",
                    file_id=str(photo["file_id"]),
                    mime_type="image/jpeg",
                    size=_int(photo.get("file_size")),
                )
            )
    document = _mapping(message.get("document"))
    if document.get("file_id"):
        result.append(
            Attachment(
                kind="document",
                file_id=str(document["file_id"]),
                file_name=_bounded(document.get("file_name"), 255),
                mime_type=_bounded(document.get("mime_type"), 127),
                size=_int(document.get("file_size")),
            )
        )
    return result


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _identifier(value: Any) -> str:
    if isinstance(value, bool) or value is None:
        return ""
    return str(value).strip()


def _int(value: Any) -> int | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _bounded(value: Any, limit: int) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text[:limit] if text else None


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text else None
