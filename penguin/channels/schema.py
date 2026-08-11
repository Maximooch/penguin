"""Small, transport-neutral contracts shared by channel adapters."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

__all__ = [
    "Attachment",
    "ChannelAddress",
    "DeliveryRequest",
    "InboundEnvelope",
    "StreamUpdate",
]


@dataclass(frozen=True)
class ChannelAddress:
    """Stable destination and session-binding identity for one channel scope."""

    platform: str
    account_id: str
    chat_id: str
    topic_id: str = ""

    @property
    def lane_key(self) -> str:
        """Return a collision-resistant per-chat/topic scheduling lane."""

        return "\x1f".join(
            (self.platform, self.account_id, self.chat_id, self.topic_id)
        )


@dataclass(frozen=True)
class Attachment:
    """Bounded external media metadata; payload bytes are never embedded."""

    kind: str
    file_id: str
    file_name: str | None = None
    mime_type: str | None = None
    size: int | None = None


@dataclass(frozen=True)
class InboundEnvelope:
    """Normalized channel input admitted before Penguin execution."""

    event_id: str
    source_sequence: int
    address: ChannelAddress
    sender_id: str
    text: str = ""
    sender_username: str | None = None
    reply_to_message_id: str | None = None
    attachments: Sequence[Attachment] = field(default_factory=tuple)
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class StreamUpdate:
    """One assistant, reasoning, or progress delta from a Penguin turn."""

    text: str
    kind: str = "assistant"
    final: bool = False


@dataclass(frozen=True)
class DeliveryRequest:
    """A durable outbound request addressed to a channel lane."""

    delivery_id: str
    address: ChannelAddress
    kind: str
    payload: Mapping[str, Any]
    reply_to_message_id: str | None = None
