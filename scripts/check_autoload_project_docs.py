#!/usr/bin/env python3
"""
Quick verification script for ConversationManager project docs autoloading.

- Creates a temp workspace
- Writes PENGUIN.md
- Instantiates ConversationManager
- Checks whether a CONTEXT message with source="project_docs" was added
"""

import os
import shutil
from pathlib import Path


def main() -> int:
    # Create temp workspace under repo root to respect sandbox writable roots
    repo_root = Path(__file__).resolve().parents[1]
    temp_ws = (repo_root / "tmp" / "autoload_ws").resolve()
    temp_ws.mkdir(parents=True, exist_ok=True)
    try:
        # Ensure env var guides any logging/util paths before importing penguin modules
        os.environ["PENGUIN_WORKSPACE"] = temp_ws.as_posix()

        # Seed project docs
        (temp_ws / "PENGUIN.md").write_text("Autoload smoke test", encoding="utf-8")

        # Import lazily to respect env vars
        from penguin.system.conversation_manager import ConversationManager
        from penguin.system.state import MessageCategory

        cm = ConversationManager(workspace_path=temp_ws)

        # Search for autoloaded CONTEXT message
        found = False
        for m in cm.conversation.session.messages:
            if m.category == MessageCategory.CONTEXT and isinstance(m.content, str):
                if (m.metadata or {}).get("source") == "project_docs" or "Project Instructions (PENGUIN.md)" in m.content:
                    found = True
                    break

        print(f"workspace={temp_ws}")
        print(f"autoloaded={'yes' if found else 'no'}")
        return 0 if found else 2
    finally:
        # Cleanup workspace folder
        try:
            shutil.rmtree(temp_ws, ignore_errors=True)
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
