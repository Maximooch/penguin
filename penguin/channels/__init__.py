"""Transport-neutral channel primitives."""

from penguin.channels.chat import ChatProcessRequest, execute_chat_turn
from penguin.channels.schema import (
    Attachment,
    ChannelAddress,
    DeliveryRequest,
    InboundEnvelope,
    StreamUpdate,
)

__all__ = [
    "Attachment",
    "ChannelAddress",
    "ChatProcessRequest",
    "DeliveryRequest",
    "InboundEnvelope",
    "StreamUpdate",
    "execute_chat_turn",
]
