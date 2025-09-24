"""Multi-agent smoke test exercising planner -> implementer -> QA handoff.

This script avoids heavy workspace setup. It creates a temporary project in the
Penguin workspace (or system temp dir if running standalone), seeds a toy
charter, and runs the three personas through a short loop to demonstrate:

* Planner reading the task and writing a concrete plan
* Implementer performing a minimal change (adding a line to a scratch file)
* QA verifying the updated file and recording a verdict

The goal is determinism and low overhead—useful for CI or manual verification
without the complexity of the live_agents demo.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from pathlib import Path
from typing import Optional

from penguin.api_client import PenguinClient, create_client
from penguin.config import WORKSPACE_PATH

ROOM = "smoke-room"

PLANNER_PROMPT = (
    "You are the planner. Read the charter at context/SMOKE_CHARTER.md, summarise the goal, "
    "and outline a short plan (1-2 steps). Do not attempt implementation."
)

IMPLEMENTER_PROMPT = (
    "You are the implementer. Read context/SMOKE_CHARTER.md, then append a line saying "
    "'Implementation done' to projects/smoke_project/log.txt. Use ActionXML apply_diff. "
    "Afterwards, record a note under 'Implementation Notes' in the charter."
)

QA_PROMPT = (
    "You are QA. Ensure projects/smoke_project/log.txt contains 'Implementation done'. "
    "Update the charter's 'QA Verification' section with Pass/Fail and exit."
)


async def multi_agent_smoke(workspace: Path, charter_path: Path, project_dir: Path) -> None:
    async with await create_client(workspace_path=str(workspace)) as client:
        client.create_agent("planner", system_prompt=PLANNER_PROMPT, activate=True)
        client.create_agent("implementer", system_prompt=IMPLEMENTER_PROMPT)
        client.create_agent("qa", system_prompt=QA_PROMPT)

        async def chat(agent_id: str, message: str) -> str:
            result = await client.core.process(
                input_data={"text": message},
                agent_id=agent_id,
                streaming=False,
                multi_step=True,
            )
            return result.get("assistant_response", "")

        # Planner outlines the work (even though the charter already contains it)
        planner_summary = await chat(
            "planner",
            "Review the charter and summarise the goal + plan for implementer.",
        )
        await client.send_to_agent(
            "implementer",
            planner_summary,
            metadata={"from": "planner"},
            channel=ROOM,
        )

        implementer_log = await chat(
            "implementer",
            "Append implementation note per instructions.",
        )
        await client.send_to_agent(
            "qa",
            implementer_log,
            metadata={"from": "implementer"},
            channel=ROOM,
        )

        qa_report = await chat("qa", "Verify implementation and update charter.")
        await client.send_to_agent(
            "planner",
            qa_report,
            metadata={"from": "qa"},
            channel=ROOM,
        )

        # Print final charter/log for convenience
        print("\n--- Charter ---")
        print(charter_path.read_text(encoding="utf-8"))
        log_path = project_dir / "log.txt"
        print("\n--- Log.txt ---")
        print(log_path.read_text(encoding="utf-8"))


def seed_environment(base_workspace: Path) -> tuple[Path, Path, Path]:
    tmp_project = tempfile.mkdtemp(prefix="penguin_smoke_", dir=str(base_workspace))
    project_dir = Path(tmp_project) / "projects" / "smoke_project"
    project_dir.mkdir(parents=True, exist_ok=True)
    charter_path = Path(tmp_project) / "context" / "SMOKE_CHARTER.md"
    charter_path.parent.mkdir(parents=True, exist_ok=True)

    charter_path.write_text(
        """# Smoke Charter

## Goal
- Append a single confirmation line to `projects/smoke_project/log.txt`.

## Implementation Notes
- Pending

## QA Verification
- Pending
""",
        encoding="utf-8",
    )
    log_path = project_dir / "log.txt"
    log_path.write_text("Initial log entry\n", encoding="utf-8")

    # Load both into the workspace context so agents can see them
    workspace = base_workspace
    # Symlink the project into the workspace projects dir for consistent paths
    workspace_project = workspace / "projects" / "smoke_project"
    if workspace_project.exists():
        if workspace_project.is_symlink():
            workspace_project.unlink()
        elif workspace_project.is_dir():
            # Best effort clean-up
            for child in workspace_project.iterdir():
                if child.is_file():
                    child.unlink()
            workspace_project.rmdir()
    workspace_project.parent.mkdir(parents=True, exist_ok=True)
    workspace_project.symlink_to(project_dir, target_is_directory=True)

    workspace_charter = workspace / "context" / "SMOKE_CHARTER.md"
    workspace_charter.parent.mkdir(parents=True, exist_ok=True)
    workspace_charter.write_text(charter_path.read_text(encoding="utf-8"), encoding="utf-8")

    return workspace, workspace_charter, workspace_project


async def main() -> None:
    workspace = WORKSPACE_PATH
    workspace, charter_path, project_dir = seed_environment(workspace)
    await multi_agent_smoke(workspace, charter_path, project_dir)


if __name__ == "__main__":
    asyncio.run(main())
