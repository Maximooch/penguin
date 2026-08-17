"""MessageBus delivery acknowledgement contracts."""

from __future__ import annotations

import pytest

from penguin.system.message_bus import MessageBus, ProtocolMessage


@pytest.mark.asyncio
async def test_missing_recipient_returns_false() -> None:
    """Publishing an event is not the same as delivering to a recipient."""

    bus = MessageBus()

    delivered = await bus.send(
        ProtocolMessage(
            sender="default",
            recipient="missing-child",
            content="hello",
        )
    )

    assert delivered is False


@pytest.mark.asyncio
async def test_registered_recipient_returns_true() -> None:
    """Successful handler completion must acknowledge delivery."""

    bus = MessageBus()
    received: list[str] = []

    async def _receive(message: ProtocolMessage) -> None:
        received.append(str(message.content))

    bus.register_handler("child", _receive)

    delivered = await bus.send(
        ProtocolMessage(
            sender="default",
            recipient="child",
            content="hello",
        )
    )

    assert delivered is True
    assert received == ["hello"]
