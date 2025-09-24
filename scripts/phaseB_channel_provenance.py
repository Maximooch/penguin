"""
Phase B – Channel Provenance

Send multiple delegated messages across channels to a sub-agent, verify that
conversation history metadata preserves channel values.

Run: python scripts/phaseB_channel_provenance.py
"""

from __future__ import annotations

import asyncio
import json
from penguin.api_client import PenguinClient
from penguin.utils.parser import CodeActAction, ActionType


async def main() -> None:
    child = "chan_child"
    async with PenguinClient() as client:
        core = client.core
        await core.action_executor.execute_action(
            CodeActAction(ActionType.SPAWN_SUB_AGENT, '{"id":"chan_child","parent":"default"}')
        )

        # Delegate to two different channels
        await core.action_executor.execute_action(
            CodeActAction(
                ActionType.DELEGATE,
                '{"parent":"default","child":"chan_child","content":"msg dev","channel":"dev-room"}',
            )
        )
        await core.action_executor.execute_action(
            CodeActAction(
                ActionType.DELEGATE,
                '{"parent":"default","child":"chan_child","content":"msg ops","channel":"ops-room"}',
            )
        )

        # Inspect history
        conv = core.conversation_manager.get_agent_conversation(child)
        sid = getattr(conv.session, "id", None)
        hist = core.get_conversation_history(sid, include_system=True, limit=50) if sid else []
        tail = [
            {
                "role": m.get("role"),
                "type": m.get("message_type"),
                "channel": (m.get("metadata") or {}).get("channel"),
                "preview": (m.get("content") or "")[:30],
            }
            for m in hist[-10:]
        ]
        print(json.dumps(tail, indent=2))


if __name__ == "__main__":
    asyncio.run(main())

