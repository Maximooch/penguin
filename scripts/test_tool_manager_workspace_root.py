#!/usr/bin/env python3
"""
Validate ToolManager operates in WORKSPACE when PENGUIN_WRITE_ROOT=workspace.

Run: PENGUIN_WRITE_ROOT=workspace python penguin/scripts/test_tool_manager_workspace_root.py
"""
import os
import sys
import tempfile
from pathlib import Path
import uuid


def log(msg: str):
    print(f"[TEST] {msg}")


def assert_true(cond: bool, msg: str):
    if not cond:
        raise AssertionError(msg)


def main():
    # Ensure no wizard and force workspace mode via env
    os.environ.setdefault("PENGUIN_NO_SETUP", "1")
    os.environ["PENGUIN_WRITE_ROOT"] = "workspace"

    from penguin.config import WORKSPACE_PATH
    from penguin.tools import ToolManager

    orig_cwd = Path.cwd()
    try:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp).resolve()
            os.environ["PENGUIN_CWD"] = str(project)
            os.chdir(project)

            tm = ToolManager(config={}, log_error_func=lambda e, m: None, fast_startup=True)
            log(f"file_root_mode: {tm.file_root_mode}")
            assert_true(tm.file_root_mode == 'workspace', "file_root_mode should be 'workspace' from env")

            tag = f"ws_mode_{uuid.uuid4().hex[:8]}"
            rel_dir = tag
            rel_file = f"{rel_dir}/in_ws.txt"
            _ = tm.execute_tool("create_folder", {"path": rel_dir})
            _ = tm.execute_tool("create_file", {"path": rel_file, "content": "WS"})

            # Verify created under workspace
            ws_path = Path(WORKSPACE_PATH) / rel_file
            assert_true(ws_path.exists(), "File should be created in workspace root")
            # Verify not under project
            assert_true(not (project / rel_file).exists(), "File should not be created in project root")

            print("\nALL TESTS PASSED ✅")
    except Exception as e:
        print(f"\nTEST FAILED ❌: {e}")
        sys.exit(1)
    finally:
        os.chdir(orig_cwd)


if __name__ == "__main__":
    main()

