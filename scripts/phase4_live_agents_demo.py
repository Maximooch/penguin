"""Live multi-agent demo that uses real LLMs and the Penguin workspace.

This script:
- Creates a tiny demo project inside the configured Penguin workspace with a deliberate bug
- Loads those project files into context for the agents
- Spins up three agents (planner, implementer, qa)
- Runs an end-to-end conversation where planner outlines a fix, implementer proposes edits,
  and QA validates the outcome

Requirements:
- Configure your model and API keys via ~/.config/penguin/config.yml or env vars
- Optionally set PENGUIN_WORKSPACE to choose a workspace directory
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import List, Optional

# Ensure workspace is set BEFORE importing penguin modules so config picks it up
os.environ.setdefault("PENGUIN_WORKSPACE", str(Path.home() / "penguin_workspace"))

from penguin.api_client import ChatOptions, PenguinClient, create_client
from penguin.config import WORKSPACE_PATH

PLANNER_SYSTEM_PROMPT = (
    "You are the Planner agent. Analyse requirements, outline steps, and delegate implementation tasks. "
    "Maintain the shared charter at context/TASK_CHARTER.md by recording goal, normalized target paths, "
    "acceptance criteria, and QA checklist. Before handing off, ensure paths are workspace-relative and "
    "call out what QA must verify. Keep responses concise and structured."
)

IMPLEMENTER_SYSTEM_PROMPT = (
    "You are the Implementer agent. Apply code changes, run tools, and report concrete modifications. "
    "Read the shared charter before acting, refuse ambiguous paths, and update the charter (or status note) "
    "with files touched, diffs produced, and verification performed so QA knows what to inspect. Prefer actionable "
    "commands over high-level discussion."
)

QA_SYSTEM_PROMPT = (
    "You are the QA agent. Validate that implementation satisfies the charter. Confirm each acceptance criterion, "
    "note any gaps back in the charter, and only give final approval when tests and manual checks pass. Escalate "
    "misalignments to planner/implementer instead of silently failing."
)

ROOM = "dev-room"


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def setup_demo_project(workspace_root: Path) -> List[str]:
    """Create a small demo project with a deliberate bug inside the workspace.

    Returns a list of file paths (as strings) to load as context.
    """
    project_dir = workspace_root / "projects" / "live_agents_demo"
    src_dir = project_dir / "src"
    tests_dir = project_dir / "tests"

    readme = project_dir / "README.md"
    module_file = src_dir / "temperature.py"
    test_file = tests_dir / "test_temperature.md"

    readme_content = (
        "# Live Agents Demo\n\n"
        "This mini-project contains a bug in `fahrenheit_to_celsius` within `src/temperature.py`.\n\n"
        "- Expected behavior: Convert Fahrenheit degrees to Celsius using the exact formula.\n"
        "- Bug: The current implementation uses an approximation that is wildly inaccurate.\n\n"
        "Your task: plan, implement, and validate a fix.\n"
    )

    module_content = (
        "from __future__ import annotations\n\n"
        "def fahrenheit_to_celsius(value_f: float) -> float:\n"
        "    \"\"\"Convert Fahrenheit to Celsius.\n\n"
        "    Should implement the exact formula `(F - 32) * 5/9`.\n"
        "    BUG: Currently uses an old approximation that is off by several degrees.\n"
        "    \"\"\"\n"
        "    # Deliberate bug: legacy rule of thumb\n"
        "    return (value_f - 30) / 2\n"
    )

    test_content = (
        "# Validation Notes for QA\n\n"
        "- `fahrenheit_to_celsius(32)` should return `0`.\n"
        "- `fahrenheit_to_celsius(212)` should return `100`.\n"
        "- Check negative values (e.g., `-40` stays `-40`) and fractional inputs.\n"
    )

    _write_text(readme, readme_content)
    _write_text(module_file, module_content)
    _write_text(test_file, test_content)

    return [str(readme), str(module_file), str(test_file)]


async def chat(client: PenguinClient, agent_id: str, message: str) -> str:
    """Send a message through the multi-step processor so actions/tools run."""
    print(f"\n[{agent_id.upper()} INPUT]\n{message}\n")
    result = await client.core.process(
        input_data={"text": message},
        agent_id=agent_id,
        streaming=False,
        multi_step=True,
    )
    assistant = result.get("assistant_response", "")
    print(f"[{agent_id.upper()} OUTPUT]\n{assistant}\n")
    if result.get("action_results"):
        print("Action results:")
        for ar in result["action_results"]:
            print(f"- {ar.get('action')}: {ar.get('status')} -> {ar.get('result')}")
        print()
    return assistant


async def main() -> None:
    # Ensure we use the configured Penguin workspace
    workspace = WORKSPACE_PATH
    os.environ.setdefault("PENGUIN_PROJECT_ROOT", str(workspace))
    print(f"Using Penguin workspace: {workspace}")

    async with await create_client(workspace_path=str(workspace)) as client:
        # Print active model info
        try:
            current = await client.get_current_model()
            if current:
                print(f"Active model: {current.provider}/{current.name}")
        except Exception:
            pass

        # Set up a minimal demo project and load its files into context
        context_files = setup_demo_project(workspace)
        project_root = Path(context_files[0]).parent.parent  # projects/live_agents_demo
        module_path = project_root / "src" / "temperature.py"
        readme_path = project_root / "README.md"
        charter_path = workspace / "context" / "TASK_CHARTER.md"
        charter_path.parent.mkdir(parents=True, exist_ok=True)
        if not charter_path.exists():
            charter_path.write_text(
                """# Task Charter\n\n"
                "## Goal\n- Pending\n\n"
                "## Scope and Paths\n- Workspace root: .\n- Pending targets\n\n"
                "## Acceptance Criteria\n- Pending\n\n"
                "## QA Checklist\n- Pending\n\n"
                "## Implementation Notes\n- Pending\n\n"
                "## QA Verification\n- Pending\n""",
                encoding="utf-8",
            )
        print(f"Demo project base_dir: {project_root}")
        await client.load_context_files(context_files + [str(charter_path)])

        project_rel_root = project_root.relative_to(workspace)
        module_rel_path = module_path.relative_to(workspace)
        readme_rel_path = readme_path.relative_to(workspace)
        charter_rel_path = charter_path.relative_to(workspace)

        # Register agents with tailored prompts
        client.create_agent("planner", system_prompt=PLANNER_SYSTEM_PROMPT, activate=True)
        client.create_agent("implementer", system_prompt=IMPLEMENTER_SYSTEM_PROMPT)
        client.create_agent("qa", system_prompt=QA_SYSTEM_PROMPT)

        # Planner analyses the bug
        planner_brief = await chat(
            client,
            "planner",
            (
                "We have a workspace project at projects/live_agents_demo. "
                "In src/temperature.py, fahrenheit_to_celsius uses an inaccurate shortcut. "
                "Outline a concise remediation plan with steps (planning only). "
                f"Write the key details (goal, normalized target paths, acceptance criteria, QA checklist) into {charter_rel_path.as_posix()} so other roles can rely on it. "
                f"Use workspace-relative paths such as {module_rel_path.as_posix()} and {readme_rel_path.as_posix()} when updating the charter."
            ),
        )

        # Share planner brief in the dev room
        await client.send_to_agent(
            "implementer",
            planner_brief,
            channel=ROOM,
            metadata={"from": "planner"},
        )

        # Implementer performs modifications
        implementer_out = await chat(
            client,
            "implementer",
            (
                "You must produce ActionXML to make changes.\n\n"
                f"Workspace-relative base directory: {project_rel_root.as_posix()}\n"
                f"Target file: {module_rel_path.as_posix()}\n"
                "Goal: apply the exact conversion formula (F - 32) * 5/9 and add any guards if needed.\n\n"
                "Steps:\n"
                f"1) Read the file (use <enhanced_read>{module_rel_path.as_posix()}:true:400</enhanced_read>).\n"
                "2) Apply a minimal diff to replace the approximation with the precise formula and update the docstring.\n"
                f"3) Optionally add/update a small README note ({readme_rel_path.as_posix()}) if needed.\n\n"
                f"Consult {charter_rel_path.as_posix()} before acting, reject ambiguous paths, and append a short summary of files changed plus verification steps under 'Implementation Notes' in {charter_rel_path.as_posix()} using apply_diff.\n\n"
                "Only communicate via ActionXML blocks so tools execute."
            ),
        )

        # Broadcast implementer output to QA in the room
        await client.send_to_agent(
            "qa", implementer_out, channel=ROOM, metadata={"from": "implementer"}
        )

        # QA validates and reports results
        qa_summary = await chat(
            client,
            "qa",
            (
                "Validate that fahrenheit_to_celsius now matches the exact formula for typical test points. "
                "List manual or automated checks you would run to confirm no regressions. "
                f"Confirm each acceptance criterion recorded in {charter_rel_path.as_posix()}. "
                f"Record your findings under 'QA Verification' (using apply_diff) and, if anything is missing, document it there and route the issue back instead of approving."
            ),
        )

        # Broadcast QA verdict back to planner and human
        await client.send_to_agent(
            "planner",
            qa_summary,
            channel=ROOM,
            metadata={"from": "qa"},
        )
        await client.send_to_human(
            qa_summary,
            channel=ROOM,
            metadata={"from": "qa"},
        )

        # Print room history for review
        print("\n=== dev-room transcripts ===")
        for agent in ("planner", "implementer", "qa"):
            # Ensure we read history from the correct agent's session manager
            cm = client.core.conversation_manager
            cm.set_current_agent(agent)
            session_id = cm.agent_sessions[agent].session.id  # type: ignore[attr-defined]
            history = cm.get_conversation_history(session_id, include_system=False)
            print(f"\nAgent: {agent} (session {session_id})")
            for entry in history:
                if entry.get("metadata", {}).get("channel") != ROOM:
                    continue
                print(
                    f"  [{entry['timestamp']}] {entry['agent_id']} -> {entry['recipient_id']}: "
                    f"{entry['content']}"
                )


if __name__ == "__main__":
    asyncio.run(main())
