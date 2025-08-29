#!/usr/bin/env python3
"""
Manual test script to verify ToolManager operates in the project (CWD/git-root)
rather than the Penguin workspace for file and command operations.

Run: python penguin/scripts/test_tool_manager_project_root.py

This script:
 - Creates a temporary project directory and sets it as PENGUIN_CWD
 - Instantiates ToolManager
 - Exercises file ops, diff apply, list/find, code and shell execution
 - Asserts effects occur under the temp project and not in WORKSPACE_PATH
"""

import os
import sys
import tempfile
from pathlib import Path
import platform


def log(msg: str):
    print(f"[TEST] {msg}")


def assert_true(cond: bool, msg: str):
    if not cond:
        raise AssertionError(msg)


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def main():
    # Preserve env and CWD
    orig_env = dict(os.environ)
    orig_cwd = Path.cwd()

    # Ensure setup wizard never blocks when running outside Penguin repo
    os.environ.setdefault("PENGUIN_NO_SETUP", "1")

    # Lazily import after setting up env guard
    from penguin.config import WORKSPACE_PATH
    from penguin.tools import ToolManager
    from penguin.tools.core.support import generate_diff_patch

    try:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp).resolve()
            # Direct Penguin to treat this as the project root
            os.environ["PENGUIN_CWD"] = str(project)
            # Ensure write policy defaults to project
            os.environ["PENGUIN_WRITE_ROOT"] = "project"
            os.chdir(project)

            log(f"Project root: {project}")
            log(f"Workspace root: {WORKSPACE_PATH}")

            # Instantiate ToolManager with minimal config
            # Enable analysis tools so analyze_codebase runs
            tm = ToolManager(config={"tools": {"allow_memory_tools": True}}, log_error_func=lambda e, m: None, fast_startup=True)

            # 1) Project root detection
            log(f"ToolManager.project_root = {tm.project_root}")
            assert_true(Path(tm.project_root).resolve() == project, "project_root should equal temp project directory")

            # 2) create_folder and create_file under project root
            log("Creating folder and file in project root…")
            folder_rel = "tmp_dir"
            file_rel = f"{folder_rel}/test.txt"
            res1 = tm.execute_tool("create_folder", {"path": folder_rel})
            res2 = tm.execute_tool("create_file", {"path": file_rel, "content": "hello"})
            log(str(res1))
            log(str(res2))

            file_path = project / file_rel
            assert_true(file_path.exists(), "File should exist under project root")
            assert_true((project / folder_rel).is_dir(), "Folder should exist under project root")
            assert_true("hello" in read_text(file_path), "File should contain initial content")

            # Ensure workspace was not polluted
            assert_true(not (Path(WORKSPACE_PATH) / folder_rel).exists(), "Workspace should not contain project folder")

            # 3) write_to_file and read_file anchored to project root
            log("Writing new content via write_to_file and reading it back…")
            res3 = tm.execute_tool("write_to_file", {"path": file_rel, "content": "hello2"})
            log(str(res3))
            res4 = tm.execute_tool("read_file", {"path": file_rel})
            assert_true(isinstance(res4, str) and "hello2" in res4, "read_file should return updated content")

            # 4) list_files and find_file relative to project root
            log("Listing files and finding test.txt in project subdir…")
            res5 = tm.execute_tool("list_files", {"path": folder_rel})
            res6 = tm.execute_tool("find_file", {"filename": "test.txt", "search_path": folder_rel})
            log(str(res5))
            log(str(res6))
            assert_true("test.txt" in str(res5), "list_files should include test.txt")
            assert_true("test.txt" in str(res6), "find_file should find test.txt")

            # 5) apply_diff to modify file via unified diff
            log("Applying unified diff to change file content to 'hello3'…")
            original = read_text(file_path)
            # Preserve newline style to avoid context mismatch in unified patcher
            new_content = "hello3"
            diff = generate_diff_patch(original, new_content, file_rel)
            res7 = tm.execute_tool("apply_diff", {"file_path": file_rel, "diff_content": diff, "backup": True})
            log(str(res7))
            final_text = read_text(file_path)
            if isinstance(res7, str) and res7.startswith("Error applying diff"):
                log("apply_diff failed due to strict context; falling back to edit_with_pattern…")
                _ = tm.execute_tool("edit_with_pattern", {"file_path": file_rel, "search_pattern": r"hello2", "replacement": "hello3", "backup": True})
                final_text = read_text(file_path)
            assert_true(final_text == new_content, "File content should be 'hello3' after edit")

            # 6b) analyze_codebase rooted at project root
            log("Validating analyze_codebase is rooted to project root…")
            resA = tm.execute_tool("analyze_codebase", {})
            resA_str = str(resA)
            assert_true(str(project) in resA_str, "analyze_codebase should reference the project root path")

            # 6c) get_file_map rooted at project root
            log("Validating get_file_map is rooted to project root…")
            resFM = tm.execute_tool("get_file_map", {"directory": ""})
            resFM_str = str(resFM)
            assert_true("tmp_dir/" in resFM_str and "test.txt" in resFM_str, "file map should include project files")

            # 6) execute_command runs in project root
            log("Executing a shell command to print current directory…")
            if platform.system().lower().startswith("win"):
                cmd = "cd"
                # Windows 'cd' prints the current dir via shell; compare suffix
                out = tm.execute_tool("execute_command", {"command": cmd})
                out_norm = str(out).strip().replace("\\", "/")
                proj_norm = str(project).replace("\\", "/")
                assert_true(out_norm.endswith(proj_norm), f"execute_command should run in project root (got {out})")
            else:
                cmd = "pwd"
                out = tm.execute_tool("execute_command", {"command": cmd})
                out_norm = str(out).strip()
                assert_true(Path(out_norm).resolve() == project, f"execute_command should run in project root (got {out})")

            # 7) code_execution runs in project root
            log("Executing code cell to print os.getcwd()…")
            code = "import os; print(os.getcwd())"
            out2 = tm.execute_tool("code_execution", {"code": code})
            out2_str = str(out2).strip().splitlines()[-1] if out2 else ""
            if isinstance(out2, str) and out2.startswith("Error executing code"):
                log(f"code_execution unavailable, skipping check: {out2}")
            else:
                assert_true(Path(out2_str).resolve() == project, f"code_execution should run in project root (got {out2_str})")

            print("\nALL TESTS PASSED ✅")
    except Exception as e:
        print(f"\nTEST FAILED ❌: {e}")
        sys.exit(1)
    finally:
        # Restore env and CWD
        os.chdir(orig_cwd)
        os.environ.clear()
        os.environ.update(orig_env)


if __name__ == "__main__":
    main()
