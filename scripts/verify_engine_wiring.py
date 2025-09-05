#!/usr/bin/env python3
"""Smoke check: Engine/CM/Core multi-agent wiring and diagnostics.

Validates that:
- Engine registry contains default + new agents
- ConversationManager tracks per-agent conversations
- smoke_check_agents() reports engine_registry=True for all registered agents

Usage:
  python -m penguin.scripts.verify_engine_wiring
"""

import asyncio
from pathlib import Path

from penguin.core import PenguinCore


async def main() -> None:
    ws = Path.cwd() / "_tmp_workspace_phase5_engine_wiring"
    ws.mkdir(parents=True, exist_ok=True)

    core = await PenguinCore.create(workspace_path=str(ws), enable_cli=False, fast_startup=True)

    # Register two agents
    core.register_agent("a1", system_prompt="You are A1.")
    core.register_agent("a2", system_prompt="You are A2.", activate=True)

    # Engine registry
    engine_agents = set(core.engine.list_agents()) if getattr(core, "engine", None) else set()

    # CM per-agent conversations
    cm_agents = set(getattr(core.conversation_manager, "agent_sessions", {}).keys())

    # Diagnostics snapshot
    snap = core.smoke_check_agents()
    engine_ok = all(snap["engine_registry"].get(a, False) for a in cm_agents)

    print("--- verify_engine_wiring results ---")
    print(f"Workspace: {ws}")
    print(f"Engine agents: {sorted(engine_agents)}")
    print(f"CM agents: {sorted(cm_agents)}")
    print(f"Engine registry mapping: {snap['engine_registry']}")
    ok = ("default" in engine_agents) and ({"a1", "a2"}.issubset(cm_agents)) and engine_ok
    print("PASS" if ok else "FAIL")


if __name__ == "__main__":
    asyncio.run(main())

