"""
Phase B – Context Sharing & Clamp Matrix

Validates:
 - Isolated child copies SYSTEM/CONTEXT once and logs clamp notice when shared_cw_max_tokens set
 - Shared session/CW child shares the same session id as parent and appears in agents_sharing_session

Run: python scripts/phaseB_context_share_matrix.py
"""

from __future__ import annotations

import asyncio
from penguin.api_client import PenguinClient


async def main() -> None:
    async with PenguinClient() as client:
        core = client.core
        cm = core.conversation_manager

        # Isolated child with clamp
        core.create_sub_agent(
            "iso_child",
            parent_agent_id="default",
            share_session=False,
            share_context_window=False,
            shared_cw_max_tokens=512,
        )

        # Look for clamp notice in iso_child history
        conv_iso = cm.get_agent_conversation("iso_child")
        sid_iso = getattr(conv_iso.session, "id", None)
        clamp_noted = False
        if sid_iso:
            hist = cm.get_conversation_history(sid_iso, include_system=True, limit=50)
            clamp_noted = any((m.get("metadata") or {}).get("type") == "cw_clamp_notice" for m in hist)
        print("[iso clamp notice]", clamp_noted)

        # Shared child (both session & context window)
        core.create_sub_agent(
            "shared_child",
            parent_agent_id="default",
            share_session=True,
            share_context_window=True,
        )
        # Verify same session id
        conv_parent = cm.get_agent_conversation("default")
        conv_shared = cm.get_agent_conversation("shared_child")
        same_session = getattr(conv_parent.session, "id", None) == getattr(conv_shared.session, "id", None)
        print("[shared same session]", same_session)

        # Verify agents_sharing_session reports both agents
        group = cm.agents_sharing_session("shared_child")
        print("[sharing group]", group)


if __name__ == "__main__":
    asyncio.run(main())

