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
    "You are the Planner agent. Focus on analyzing requirements, outlining steps, and "
    "delegating implementation tasks. Keep responses concise and structured."
)

IMPLEMENTER_SYSTEM_PROMPT = (
    "You are the Implementer agent. Apply code changes, run tools, and report concrete "
    "modifications. Prefer actionable commands over high-level discussion."
)

QA_SYSTEM_PROMPT = (
    "You are the QA agent. Verify fixes, design tests, and report validation results."
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
    module_file = src_dir / "numbers.py"
    test_file = tests_dir / "test_numbers.md"

    readme_content = (
        "# Live Agents Demo\n\n"
        "This mini-project contains a bug in `summarize_numbers` within `src/numbers.py`.\n\n"
        "- Expected behavior: Return a dict with `count`, `sum`, `mean` for a list of numbers.\n"
        "- Bug: When given an empty list, it raises `ValueError` instead of returning a safe summary\n"
        "  such as `{count: 0, sum: 0, mean: 0}`.\n\n"
        "Your task: plan, implement, and validate a fix.\n"
    )

    module_content = (
        "from __future__ import annotations\n\n"
        "from typing import Dict, List\n\n"
        "def summarize_numbers(values: List[float]) -> Dict[str, float]:\n"
        "    \"\"\"Summarize a list of numbers.\n\n"
        "    Expected keys: count, sum, mean.\n"
        "    BUG: Currently raises on empty input; should return zeros.\n"
        "    \"\"\"\n"
        "    if not isinstance(values, list):\n"
        "        raise TypeError(\"values must be a list\")\n\n"
        "    # Deliberate bug: raises on empty instead of returning zeros\n"
        "    if len(values) == 0:\n"
        "        raise ValueError(\"values must not be empty\")\n\n"
        "    total = sum(values)\n"
        "    count = float(len(values))\n"
        "    mean = total / count\n"
        "    return {\"count\": count, \"sum\": float(total), \"mean\": float(mean)}\n"
    )

    test_content = (
        "# Validation Notes for QA\n\n"
        "- `summarize_numbers([1, 2, 3])` should yield `{count: 3, sum: 6, mean: 2}`.\n"
        "- `summarize_numbers([])` should not raise; expect `{count: 0, sum: 0, mean: 0}`.\n"
        "- Non-list input should raise `TypeError`.\n"
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
        module_path = project_root / "src" / "numbers.py"
        readme_path = project_root / "README.md"
        print(f"Demo project base_dir: {project_root}")
        await client.load_context_files(context_files)

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
                "In src/numbers.py, summarize_numbers([]) raises ValueError. "
                "Outline a concise remediation plan with steps (planning only)."
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
                f"Base directory (operate ONLY under this path): {project_root}\n"
                f"Target file: {module_path}\n"
                "Goal: empty list should return {count: 0, sum: 0, mean: 0} and not raise.\n\n"
                "Steps:\n"
                f"1) Read the file (use <enhanced_read>{module_path}:true:400</enhanced_read>).\n"
                "2) Apply a minimal diff to implement the behavior (use <apply_diff>...</apply_diff> with a unified diff).\n"
                f"3) Optionally add/update a small README note ({readme_path}) if needed.\n\n"
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
                "Validate that summarize_numbers([]) now returns zeros and does not raise. "
                "List manual or automated checks you would run to confirm no regressions."
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
