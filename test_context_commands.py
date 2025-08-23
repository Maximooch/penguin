#!/usr/bin/env python
"""
Tests for /context commands implemented in interface:
 - /context write <rel> --body "text"
 - /context edit <rel> --replace A --with B
 - /context note "Title" --body "text"
 - /context add <path> [--project|--workspace] [--as name]
 - /context remove <rel>

Runs against the live interface to exercise command paths.
"""

import os
import json
from pathlib import Path

from penguin.core import PenguinCore
from penguin.cli.interface import PenguinInterface
from penguin.config import WORKSPACE_PATH, load_config


def print_result(label, ok):
    status = "✅" if ok else "❌"
    print(f"{status} {label}")
    return ok


async def run():
    cfg = load_config()
    scratch = cfg.get('context', {}).get('scratchpad_dir', 'context')
    ctx_dir = Path(WORKSPACE_PATH) / scratch
    ctx_dir.mkdir(parents=True, exist_ok=True)

    core = await PenguinCore.create(show_progress=False, fast_startup=True)
    interface = PenguinInterface(core)

    # 1) write
    res = await interface._handle_context_command(["write", "tmp/test.txt", "--body", "hello world"])
    ok = isinstance(res, dict) and res.get("status") == "ok"
    print_result("/context write", ok)

    # 2) edit
    res = await interface._handle_context_command(["edit", "tmp/test.txt", "--replace", "world", "--with", "penguin"])
    ok = isinstance(res, dict) and res.get("status") == "ok"
    print_result("/context edit", ok)
    content = (ctx_dir / "tmp" / "test.txt").read_text(encoding="utf-8")
    print_result("edit applied", "penguin" in content)

    # 3) note
    res = await interface._handle_context_command(["note", "MyTitle", "--body", "note body"])
    ok = isinstance(res, dict) and res.get("status") == "ok"
    print_result("/context note", ok)

    # 4) add (from workspace to workspace, using --workspace)
    # create a source file under workspace for a safe copy
    src_file = ctx_dir / "tmp" / "src.txt"
    src_file.parent.mkdir(parents=True, exist_ok=True)
    src_file.write_text("copy me", encoding="utf-8")
    res = await interface._handle_context_command(["add", str(src_file), "--workspace", "--as", "copied.txt"])
    ok = isinstance(res, dict) and res.get("status") == "ok"
    print_result("/context add --workspace", ok)
    print_result("add created file", (ctx_dir / "copied.txt").exists())

    # 5) remove
    res = await interface._handle_context_command(["remove", "copied.txt"])
    ok = isinstance(res, dict) and res.get("status") == "ok"
    print_result("/context remove", ok)
    print_result("remove deleted file", not (ctx_dir / "copied.txt").exists())


def main():
    import asyncio
    print("\n🧪 Testing context commands (/context ... )\n")
    try:
        asyncio.run(run())
        return 0
    except Exception as e:
        print(f"💥 Context command test failed: {e}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())


