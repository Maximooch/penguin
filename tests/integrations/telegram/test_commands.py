from __future__ import annotations

from types import SimpleNamespace

import pytest

from penguin.channels.schema import ChannelAddress, InboundEnvelope
from penguin.integrations.telegram._commands import handle_command
from penguin.integrations.telegram.config import TelegramConfig


@pytest.mark.asyncio
async def test_permissions_command_is_read_only_and_reports_effective_policy() -> None:
    config = TelegramConfig.from_mapping(
        {
            "security": {"mode": "read_only"},
            "channels": {
                "telegram": {
                    "permissions": {
                        "mode": "full_access",
                        "approvals": {
                            "shell": "ask",
                            "fileWrite": "deny",
                            "default": "allow",
                        },
                        "timeout_seconds": 60,
                    }
                }
            },
        },
        {},
    )
    manager = SimpleNamespace(store=object(), config=config)
    envelope = InboundEnvelope(
        event_id="telegram:test:1",
        source_sequence=1,
        address=ChannelAddress(
            platform="telegram",
            account_id="test",
            chat_id="42",
        ),
        sender_id="42",
        text="/permissions",
    )
    binding = SimpleNamespace(session_id="session-1")

    response = await handle_command(
        manager,
        "permissions",
        "ignored",
        envelope,
        binding,
    )

    assert response is not None
    assert "Mode cap: read_only" in response
    assert "Telegram category decisions:" in response
    assert "- shell: ask" in response
    assert "- fileWrite: deny" in response
    assert "- default: allow" in response
    assert "Approval timeout: 60 seconds" in response
    assert "instance or agent policy can still ASK" in response
    assert "workspace DENY still blocks" in response


@pytest.mark.asyncio
async def test_help_advertises_permissions_command() -> None:
    manager = SimpleNamespace(store=object(), config=TelegramConfig())
    envelope = InboundEnvelope(
        event_id="telegram:test:2",
        source_sequence=2,
        address=ChannelAddress(
            platform="telegram",
            account_id="test",
            chat_id="42",
        ),
        sender_id="42",
    )

    response = await handle_command(
        manager,
        "help",
        "",
        envelope,
        SimpleNamespace(session_id="session-1"),
    )

    assert response is not None
    assert "/permissions" in response
