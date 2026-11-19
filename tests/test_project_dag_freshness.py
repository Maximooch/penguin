"""DAG views reflect the tasks as they are now.

Covers SM-75 (DAG cache): ``build_dag`` cached the graph per project and only a
blueprint sync cleared it, so stats and the DOT export kept showing tasks,
edges and statuses from the first build after tasks changed.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from penguin.project.manager import ProjectManager
from penguin.project.models import TaskStatus

if TYPE_CHECKING:
    from pathlib import Path


def test_dag_views_follow_task_changes(tmp_path: Path) -> None:
    manager = ProjectManager(tmp_path)
    project = manager.create_project("DAG", "freshness")
    first = manager.create_task("First", "a", project_id=project.id)
    assert manager.get_dag_stats(project.id)["total_tasks"] == 1

    manager.create_task("Second", "b", project_id=project.id, dependencies=[first.id])
    manager.update_task_status(first.id, TaskStatus.RUNNING)

    stats = manager.get_dag_stats(project.id)
    assert stats["total_edges"] == 1
    assert stats["critical_path_length"] == 2
    assert "[running]" in manager.export_dag_dot(project.id)
