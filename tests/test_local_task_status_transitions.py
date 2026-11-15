"""Legacy local_task status changes go through the transition table.

Covers SM-65: several paths set ``task.status`` directly, so a cancelled or
archived task could be marked completed, and ``transition_to`` forced the new
status anyway when it hit an error.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from penguin.local_task.manager import ProjectManager

if TYPE_CHECKING:
    from pathlib import Path


def _cancelled_task(tmp_path: Path) -> tuple[ProjectManager, object]:
    manager = ProjectManager(tmp_path)
    manager.create_task("Ship it", "Release the build")
    task = manager._find_task_by_name("Ship it")
    assert task is not None
    assert task.transition_to("cancelled")
    return manager, task


def test_complete_task_refuses_a_cancelled_task(tmp_path: Path) -> None:
    manager, task = _cancelled_task(tmp_path)

    result = manager.complete_task("Ship it")

    assert task.status == "cancelled"
    assert result["status"] == "error"


def test_completing_twice_is_not_an_invalid_transition(tmp_path: Path) -> None:
    manager = ProjectManager(tmp_path)
    manager.create_task("Ship it", "Release the build")
    task = manager._find_task_by_name("Ship it")
    assert task is not None

    assert task.transition_to("completed") is True
    assert task.transition_to("completed") is True
    assert [entry["to"] for entry in task.transition_history] == ["completed"]
