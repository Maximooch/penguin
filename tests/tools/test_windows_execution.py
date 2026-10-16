"""Native Windows regression coverage for issue #124 (no Bash required)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from penguin.tools.process_runtime import ProcessRuntime
from penguin.tools.python_execution import execute_python

pytestmark = pytest.mark.skipif(os.name != "nt", reason="Windows pipe contract")


def command(code: str) -> str:
    return subprocess.list2cmdline([sys.executable, "-u", "-X", "utf8", "-c", code])


@pytest.fixture
def runtime(tmp_path):
    instance = ProcessRuntime(log_dir=tmp_path)
    yield instance
    instance.cleanup()


def finish(runtime, process_id):
    result = runtime.poll(process_id, wait_ms=5000, wait_for_exit=True)
    assert result["process_status"] == "exited", result
    assert result["reader_error"] is None, result
    return result


def test_immediate_exit_delayed_poll_replay_and_log(runtime):
    pid = runtime.start("echo command-ok & echo problem 1>&2")["process_id"]
    time.sleep(0.2)
    result = finish(runtime, pid)
    assert result["returncode"] == 0
    assert "command-ok" in result["output"]
    assert "problem" in result["output"]
    assert runtime.poll(pid)["output"] == result["output"]
    assert "command-ok" in Path(result["log_path"]).read_text(encoding="utf-8")


def test_unicode_both_streams_and_nonzero_exit(runtime):
    pid = runtime.start(
        command("import sys;print('\u96ea');print('oops',file=sys.stderr);sys.exit(7)")
    )["process_id"]
    result = finish(runtime, pid)
    assert "\u96ea" in result["output"]
    assert "oops" in result["output"]
    assert result["returncode"] == 7
    assert result["error"] == "command_failed"


def test_stdin_and_deadline_with_quiet_stderr(runtime):
    pid = runtime.start(command("print(input(),flush=True)"))["process_id"]
    written = runtime.write_stdin(pid, "ping\n")
    assert written["bytes_written"] == 5, written
    assert "ping" in finish(runtime, pid)["output"]
    pid = runtime.start(command("import time;time.sleep(30)"), timeout_seconds=0.2)[
        "process_id"
    ]
    assert finish(runtime, pid)["completion_reason"] == "timeout"


def test_full_stdin_is_bounded(runtime):
    pid = runtime.start(command("import time;time.sleep(30)"))["process_id"]
    started = time.monotonic()
    result = runtime.write_stdin(pid, "x" * 1000000, timeout_ms=100)
    assert time.monotonic() - started < 2
    assert result["error"] == "stdin_write_timeout", result
    assert 0 < result["bytes_written"] < result["bytes_total"]


def test_completion_notice_has_exit_fields(runtime):
    notices = []
    pid = runtime.start(
        "echo done",
        on_event=lambda kind, data: notices.append((kind, data)),
        notify_on_complete=True,
    )["process_id"]
    finish(runtime, pid)
    runtime._processes[pid].reader.join(2)
    completed = [data for kind, data in notices if kind == "completed"]
    assert len(completed) == 1
    assert completed[0]["returncode"] == 0
    assert completed[0]["completion_reason"] == "exited"


def test_python_timeout_then_independent_call(tmp_path):
    result = json.loads(
        execute_python("import time;time.sleep(30)", cwd=str(tmp_path), timeout=0.2)
    )
    assert result["error"] == "timeout"
    assert "healthy" in execute_python("print('healthy')", cwd=str(tmp_path), timeout=5)


def test_timeout_stops_descendant(runtime, tmp_path):
    marker = tmp_path / "child-finished.txt"
    child = (
        "import time;from pathlib import Path;time.sleep(2);"
        f"Path({str(marker)!r}).write_text('leaked')"
    )
    parent = (
        "import subprocess,sys,time;"
        f"subprocess.Popen([sys.executable,'-c',{child!r}]);"
        "print('spawned',flush=True);time.sleep(30)"
    )
    pid = runtime.start(command(parent), timeout_seconds=0.5)["process_id"]
    assert finish(runtime, pid)["completion_reason"] == "timeout"
    time.sleep(2.2)
    assert not marker.exists()


def test_public_shell_tools_retain_output(tmp_path):
    from penguin.tools.tool_manager import ToolManager

    manager = ToolManager({}, lambda *_: None, fast_startup=True)
    manager._permission_enabled = False
    try:
        result = manager.execute_tool(
            "execute_command", {"command": "echo public-ok", "cwd": str(tmp_path)}
        )
        assert isinstance(result, dict), result
        assert result["returncode"] == 0, result
        assert "public-ok" in result["output"]
    finally:
        manager.process_tools.cleanup()


def test_large_snippet_and_local_import(tmp_path):
    (tmp_path / "local_module.py").write_text("value = 42", encoding="utf-8")
    code = "# padding\n" * 2000 + "import local_module;print(local_module.value)"
    assert "42" in execute_python(code, cwd=str(tmp_path), timeout=5)


def test_public_manager_python_recovers(tmp_path, monkeypatch):
    from penguin.tools.tool_manager import ToolManager

    manager = ToolManager({}, lambda *_: None, fast_startup=True)
    monkeypatch.setenv("PENGUIN_TOOL_TIMEOUT_CODE", "1")
    failed = json.loads(
        manager.execute_code("import time;time.sleep(30)", cwd=str(tmp_path))
    )
    assert failed["error"] == "timeout"
    assert "recovered" in manager.execute_code("print('recovered')", cwd=str(tmp_path))
    assert manager._notebook_executor is None


def test_create_file_utf8(tmp_path):
    from penguin.tools.core.support import create_file

    path = tmp_path / "unicode.txt"
    result = create_file(str(path), "\u96ea", workspace_path=str(tmp_path))
    assert "successfully" in result
    assert path.read_text(encoding="utf-8") == "\u96ea"


def test_python_exception_and_parent_state(tmp_path):
    cwd = os.getcwd()
    stdout = sys.stdout
    result = json.loads(
        execute_python("raise ValueError('expected')", cwd=str(tmp_path), timeout=5)
    )
    assert "expected" in result["output"]
    assert result["returncode"] != 0
    assert os.getcwd() == cwd
    assert sys.stdout is stdout
