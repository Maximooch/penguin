"""ActionXML process tags run on the same process runtime as the native tools.

Covers SM-66: the legacy ``process_*`` ActionXML tags used a separate
ProcessManager. Exiting a session closed the child's stdin for good, and
starting a second process under the same name orphaned the first, still
running and impossible to stop.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest

from penguin.tools.process_runtime import ProcessRuntime
from penguin.tools.tool_manager import ToolManager
from penguin.utils.parser import ActionExecutor

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

pytestmark = pytest.mark.skipif(os.name == "nt", reason="POSIX shell commands")


@pytest.fixture
def executor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[ActionExecutor]:
    monkeypatch.setenv("PENGUIN_YOLO", "1")
    manager = ToolManager({}, lambda *_args: None, fast_startup=True)
    manager._process_runtime = ProcessRuntime(log_dir=tmp_path)
    yield ActionExecutor(manager, None)
    manager.process_runtime.cleanup(mode="kill", timeout=0.5)


@pytest.mark.asyncio
async def test_a_session_can_be_exited_and_entered_again(
    executor: ActionExecutor,
) -> None:
    await executor._process_start("echo-loop: while read line; do echo got:$line; done")
    await executor._process_enter("echo-loop")
    first = await executor._process_send("one")
    await executor._process_exit("")

    await executor._process_enter("echo-loop")
    second = await executor._process_send("two")

    assert "got:one" in first
    assert "got:two" in second


@pytest.mark.asyncio
async def test_reusing_a_name_does_not_orphan_the_running_process(
    executor: ActionExecutor,
) -> None:
    await executor._process_start("worker: sleep 30")
    reused = await executor._process_start("worker: sleep 30")
    stopped = await executor._process_stop("worker")

    assert "already" in reused.lower() or "exists" in reused.lower()
    assert "not found" not in stopped.lower()
    listed = await executor._process_list("")
    assert "running" not in listed.lower()
