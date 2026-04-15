from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from penguin.project.manager import ProjectManager
from penguin.project.models import ArtifactEvidence, TaskDependency, TaskPhase, TaskStatus


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed deterministic surface verification data.")
    parser.add_argument("--workspace", required=True, help="Workspace directory to seed")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Delete the target workspace before seeding",
    )
    args = parser.parse_args()

    workspace = Path(args.workspace).expanduser().resolve()
    if args.reset and workspace.exists():
        shutil.rmtree(workspace)

    workspace.mkdir(parents=True, exist_ok=True)

    manager = ProjectManager(workspace)
    project = manager.create_project(
        "Surface Verification Demo",
        "Fixture project for CLI and web surface verification.",
        workspace_path=str(workspace / "demo-project"),
    )

    active_task = manager.create_task("Active task", "Schedulable task", project_id=project.id, priority=1)
    running_task = manager.create_task("Running task", "Executing task", project_id=project.id, priority=2)
    manager.update_task_status(running_task.id, TaskStatus.RUNNING, "Fixture seed running")

    pending_review_task = manager.create_task(
        "Pending review task",
        "Ready for review approval",
        project_id=project.id,
        priority=3,
    )
    manager.update_task_status(
        pending_review_task.id,
        TaskStatus.RUNNING,
        "Fixture seed pending review",
    )
    pending_review_live = manager.get_task(pending_review_task.id)
    pending_review_live.phase = TaskPhase.DONE
    pending_review_live.mark_pending_review("Fixture ready for approval", reviewer="fixture")
    manager.storage.update_task(pending_review_live)

    completed_task = manager.create_task(
        "Completed task",
        "Already completed fixture task",
        project_id=project.id,
        priority=4,
    )
    manager.update_task_status(completed_task.id, TaskStatus.RUNNING, "Fixture seed completed")
    completed_live = manager.get_task(completed_task.id)
    completed_live.phase = TaskPhase.DONE
    completed_live.mark_pending_review("Fixture review", reviewer="fixture")
    completed_live.approve("fixture", notes="Fixture complete")
    manager.storage.update_task(completed_live)

    failed_task = manager.create_task("Failed task", "Failed fixture task", project_id=project.id, priority=5)
    manager.update_task_status(failed_task.id, TaskStatus.RUNNING, "Fixture seed failed")
    manager.update_task_status(failed_task.id, TaskStatus.FAILED, "Fixture forced failure")

    rich_task = manager.create_task(
        "Rich payload task",
        "Task with dependency, artifact, recipe, and clarification metadata",
        project_id=project.id,
        priority=2,
    )
    rich_live = manager.get_task(rich_task.id)
    rich_live.phase = TaskPhase.IMPLEMENT
    rich_live.dependencies = [active_task.id]
    rich_live.dependency_specs = [
        TaskDependency(
            task_id=active_task.id,
            policy="artifact_ready",
            artifact_key="client_bundle",
        )
    ]
    rich_live.artifact_evidence = [
        ArtifactEvidence(
            key="client_bundle",
            kind="file",
            producer_task_id=rich_live.id,
            path="dist/client_bundle.js",
            valid=True,
        )
    ]
    rich_live.recipe = "happy-path"
    rich_live.metadata = {
        "fixture": True,
        "clarification_requests": [
            {
                "task_id": rich_live.id,
                "task_status": rich_live.status.value,
                "task_phase": rich_live.phase.value,
                "prompt": "Choose auth mode",
                "status": "open",
                "requested_at": _iso_now(),
            }
        ],
    }
    manager.storage.update_task(rich_live)

    payload = {
        "workspace": str(workspace),
        "project": {
            "id": project.id,
            "name": project.name,
            "workspace_path": str(project.workspace_path) if project.workspace_path else None,
        },
        "tasks": {
            "active": active_task.id,
            "running": running_task.id,
            "pending_review": pending_review_task.id,
            "completed": completed_task.id,
            "failed": failed_task.id,
            "rich_payload": rich_task.id,
        },
    }
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
