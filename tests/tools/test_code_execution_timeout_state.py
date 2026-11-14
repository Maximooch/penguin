"""A timed-out in-process execution is reported as busy until it ends (SM-29)."""

from __future__ import annotations

import json
import threading
import time

import pytest

from penguin.tools.tool_manager import ToolManager


class _Executor:
    def __init__(self) -> None:
        self.active_directory = None
        self.release = threading.Event()
        self.calls: list[str] = []

    def execute_code(self, code: str) -> str:
        self.calls.append(code)
        if code == "block":
            self.release.wait(timeout=30)
        return f"ran {code}"


@pytest.fixture
def manager(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("PENGUIN_TOOL_TIMEOUT_CODE", "1")
    monkeypatch.delenv("PENGUIN_HOSTED", raising=False)
    executor = _Executor()
    tool_manager = ToolManager({}, lambda *_: None, fast_startup=True)
    monkeypatch.setattr(
        ToolManager, "notebook_executor", property(lambda self: executor)
    )
    yield tool_manager, executor
    executor.release.set()


def test_call_after_a_timeout_reports_busy_without_waiting(manager) -> None:
    tool_manager, executor = manager

    first = json.loads(tool_manager.execute_code("block"))
    started = time.perf_counter()
    second = json.loads(tool_manager.execute_code("next"))
    waited = time.perf_counter() - started

    assert first["error"] == "timeout"
    assert second["error"] == "code_execution_busy"
    assert waited < 0.5
    assert executor.calls == ["block"]


def test_execution_resumes_once_the_abandoned_run_ends(manager) -> None:
    tool_manager, executor = manager
    tool_manager.execute_code("block")

    executor.release.set()
    deadline = time.time() + 5
    result = ""
    while time.time() < deadline:
        result = tool_manager.execute_code("after")
        if result == "ran after":
            break
        time.sleep(0.05)

    assert result == "ran after"
