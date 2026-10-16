"""Isolated Windows Python execution using the managed process lifecycle."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

from penguin.tools.process_runtime import ProcessRuntime


def execute_python(code: str, *, cwd: str, timeout: float) -> str:
    """Run a fresh interpreter, without mutating parent streams or cwd.

    This is process isolation, not a security sandbox. Variables do not persist
    between calls. A script file avoids cmd.exe's command-line size limit.
    """
    runtime = ProcessRuntime()
    with tempfile.TemporaryDirectory(prefix="penguin-python-") as directory:
        script = Path(directory) / "execution.py"
        script.write_text(code, encoding="utf-8")
        command = subprocess.list2cmdline(
            [
                sys.executable,
                "-u",
                "-X",
                "utf8",
                "-c",
                "import runpy,sys;runpy.run_path(sys.argv[1],run_name='__main__')",
                str(script),
            ]
        )
        try:
            result = runtime.start(command, cwd=cwd, timeout_seconds=timeout)
            if result["status"] == "error":
                return json.dumps(result)
            process_id = result["process_id"]
            while result.get("process_status") != "exited":
                result = runtime.poll(
                    process_id, wait_ms=1000, wait_for_exit=True, max_chars=12000
                )
                if result.get("reader_error"):
                    return json.dumps({**result, "tool": "code_execution"})
            if result.get("error"):
                return json.dumps({**result, "tool": "code_execution"})
            return result["output"] or "Code executed successfully"
        finally:
            runtime.cleanup()


__all__ = ["execute_python"]
