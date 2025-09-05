#!/usr/bin/env python3
"""Smoke check: Snapshot create / restore / branch per-agent.

Creates a snapshot for default agent, restores it, and branches into a new
session. Verifies snapshot IDs exist and session switching works.

Usage:
  python -m penguin.scripts.verify_snapshot_branch
"""

import asyncio
from pathlib import Path

from penguin.core import PenguinCore
from penguin.system.state import MessageCategory


async def main() -> None:
    ws = Path.cwd() / "_tmp_workspace_phase5_snapshot"
    ws.mkdir(parents=True, exist_ok=True)

    core = await PenguinCore.create(workspace_path=str(ws), enable_cli=False, fast_startup=True)
    cm = core.conversation_manager

    # Seed some content
    conv = cm.get_agent_conversation(cm.current_agent_id)
    conv.add_message("system", "Seed note", category=MessageCategory.SYSTEM)
    cm.save()

    snap_id = cm.create_snapshot(meta={"name": "seed"})
    restored = cm.restore_snapshot(snap_id) if snap_id else False
    branched_id = cm.branch_from_snapshot(snap_id, meta={"name": "branch"}) if snap_id else None

    print("--- verify_snapshot_branch results ---")
    print(f"Workspace: {ws}")
    print(f"snapshot_id: {snap_id}")
    print(f"restored: {restored}")
    print(f"branched_id: {branched_id}")

    ok = bool(snap_id) and restored and bool(branched_id)
    print("PASS" if ok else "FAIL")


if __name__ == "__main__":
    asyncio.run(main())

