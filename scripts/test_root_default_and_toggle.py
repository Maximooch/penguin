#!/usr/bin/env python3
"""
Validate ToolManager default root is 'project' and runtime toggle works.

Run: python penguin/scripts/test_root_default_and_toggle.py
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
    # Prevent setup wizard on import; prefer project for writes unless toggled
    os.environ.setdefault("PENGUIN_NO_SETUP", "1")
    os.environ.pop("PENGUIN_WRITE_ROOT", None)

    from penguin.config import WORKSPACE_PATH
    from penguin.tools import ToolManager

    orig_cwd = Path.cwd()
    try:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp).resolve()
            os.environ["PENGUIN_CWD"] = str(project)
            os.chdir(project)

            tm = ToolManager(config={}, log_error_func=lambda e, m: None, fast_startup=True)
            log(f"Initial file_root_mode: {tm.file_root_mode}")
            assert_true(tm.file_root_mode == 'project', "Default file_root_mode should be 'project'")

            # Create a unique directory name to avoid collisions
            tag = f"root_toggle_{uuid.uuid4().hex[:8]}"

            # Create under project
            rel_dir = tag
            rel_file_p = f"{rel_dir}/project.txt"
            _ = tm.execute_tool("create_folder", {"path": rel_dir})
            _ = tm.execute_tool("create_file", {"path": rel_file_p, "content": "P"})
            proj_path = project / rel_file_p
            assert_true(proj_path.exists(), "Project file should exist under project root")
            # Ensure not created under workspace
            assert_true(not (Path(WORKSPACE_PATH) / rel_file_p).exists(), "Project file should not be in workspace")

            # Toggle to workspace and create another file
            msg = tm.set_execution_root('workspace')
            log(msg)
            rel_file_w = f"{rel_dir}/workspace.txt"
            _ = tm.execute_tool("create_file", {"path": rel_file_w, "content": "W"})
            ws_path = Path(WORKSPACE_PATH) / rel_file_w
            assert_true(ws_path.exists(), "Workspace file should exist under workspace root")
            # Ensure not created under project
            assert_true(not (project / rel_file_w).exists(), "Workspace file should not be in project root")

            print("\nALL TESTS PASSED ✅")
    except Exception as e:
        print(f"\nTEST FAILED ❌: {e}")
        sys.exit(1)
    finally:
        os.chdir(orig_cwd)


if __name__ == "__main__":
    main()

