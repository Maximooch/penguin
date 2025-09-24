"""
Phase A – Sub-Agent Tools Smoke Test

This script exercises the new agents-as-tools flow without invoking the LLM:
 - spawn_sub_agent (isolated by default, optional initial_prompt)
 - delegate (send message to child and log delegation)
 - stop_sub_agent / resume_sub_agent
 - verify roster state and conversation history provenance

Run:
  uv run python scripts/phaseA_sub_agent_tools_smoke.py
or
  python scripts/phaseA_sub_agent_tools_smoke.py
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Dict

from penguin.api_client import PenguinClient
from penguin.utils.parser import CodeActAction, ActionType


async def main() -> None:
    child_id = "researcher"
    parent_id = "default"  # Use default as the parent unless you registered another

    async with PenguinClient() as client:
        core = client.core

        # 1) Spawn sub-agent (isolated session/CW by default) with an initial prompt
        spawn_payload: Dict[str, Any] = {
            "id": child_id,
            "parent": parent_id,
            "persona": "research",
            "share_session": False,
            "share_context_window": False,
            "shared_cw_max_tokens": 512,
            "initial_prompt": "Summarize docs in /docs",
        }
        act_spawn = CodeActAction(ActionType.SPAWN_SUB_AGENT, json.dumps(spawn_payload))
        spawn_result = await core.action_executor.execute_action(act_spawn)
        print("[spawn_sub_agent]", spawn_result)

        # Verify mapping
        sub_map = core.list_sub_agents(parent_id)
        print("[list_sub_agents]", sub_map)

        # 2) Delegate a task to the child
        delegate_payload = {
            "parent": parent_id,
            "child": child_id,
            "content": "Audit README for gaps and report key missing topics.",
            "channel": "dev-room",
            "metadata": {"priority": "high"},
        }
        act_delegate = CodeActAction(ActionType.DELEGATE, json.dumps(delegate_payload))
        delegate_result = await core.action_executor.execute_action(act_delegate)
        print("[delegate]", delegate_result)

        # 3) Pause and resume the child
        act_pause = CodeActAction(ActionType.STOP_SUB_AGENT, json.dumps({"id": child_id}))
        pause_result = await core.action_executor.execute_action(act_pause)
        print("[stop_sub_agent]", pause_result)

        roster = core.get_agent_roster()
        child_entry = next((r for r in roster if r.get("id") == child_id), None)
        print("[roster after pause]", child_entry)

        act_resume = CodeActAction(ActionType.RESUME_SUB_AGENT, json.dumps({"id": child_id}))
        resume_result = await core.action_executor.execute_action(act_resume)
        print("[resume_sub_agent]", resume_result)

        roster = core.get_agent_roster()
        child_entry = next((r for r in roster if r.get("id") == child_id), None)
        print("[roster after resume]", child_entry)

        # 4) Inspect child conversation history for provenance
        try:
            conv = core.conversation_manager.get_agent_conversation(child_id)
            session_id = getattr(conv.session, "id", None)
            if session_id:
                history = core.get_conversation_history(session_id, include_system=True, limit=50)
                # Show a compact view of last few messages
                compact = [
                    {
                        "role": m.get("role"),
                        "type": m.get("message_type"),
                        "agent": m.get("agent_id"),
                        "recipient": m.get("recipient_id"),
                        "channel": (m.get("metadata") or {}).get("channel"),
                        "content_preview": (m.get("content") or "")[:60],
                    }
                    for m in history[-10:]
                ]
                print("[child history tail]", json.dumps(compact, ensure_ascii=False, indent=2))
                if history:
                    last_meta = (history[-1].get("metadata") or {})
                    print("[last message metadata]", json.dumps(last_meta, ensure_ascii=False, indent=2))
            else:
                print("[history] No session id for child agent")
        except Exception as e:
            print("[history] error:", e)


if __name__ == "__main__":
    asyncio.run(main())
