"""
Phase B – Pause/Resume During Delegation

Pauses a child, sends a delegated message, verifies it logs, then resumes and
checks that state notes bracket the timeline.

Run: python scripts/phaseB_pause_resume_during_delegate.py
"""

from __future__ import annotations

import asyncio
import json
from penguin.api_client import PenguinClient
from penguin.utils.parser import CodeActAction, ActionType


async def main() -> None:
    child = "pause_delegate_child"
    async with PenguinClient() as client:
        core = client.core
        await core.action_executor.execute_action(
            CodeActAction(ActionType.SPAWN_SUB_AGENT, '{"id":"pause_delegate_child","parent":"default"}')
        )
        # Pause
        await core.action_executor.execute_action(
            CodeActAction(ActionType.STOP_SUB_AGENT, '{"id":"pause_delegate_child"}')
        )
        # Delegate while paused
        await core.action_executor.execute_action(
            CodeActAction(
                ActionType.DELEGATE,
                '{"parent":"default","child":"pause_delegate_child","content":"work while paused","channel":"dev-room"}',
            )
        )
        # Resume
        await core.action_executor.execute_action(
            CodeActAction(ActionType.RESUME_SUB_AGENT, '{"id":"pause_delegate_child"}')
        )

        # Inspect child history tail
        conv = core.conversation_manager.get_agent_conversation(child)
        sid = getattr(conv.session, "id", None)
        hist = core.get_conversation_history(sid, include_system=True, limit=50) if sid else []
        tail = [
            {
                "role": m.get("role"),
                "type": m.get("message_type"),
                "meta_type": (m.get("metadata") or {}).get("type"),
                "paused": (m.get("metadata") or {}).get("paused"),
                "content": (m.get("content") or "")[:40],
            }
            for m in hist[-10:]
        ]
        print(json.dumps(tail, indent=2))


if __name__ == "__main__":
    asyncio.run(main())

