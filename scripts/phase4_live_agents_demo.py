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
import re
from pathlib import Path
from typing import List, Optional

# Ensure workspace is set BEFORE importing penguin modules so config picks it up
os.environ.setdefault("PENGUIN_WORKSPACE", str(Path.home() / "penguin_workspace"))

from penguin.api_client import ChatOptions, PenguinClient, create_client
from penguin.config import WORKSPACE_PATH

PLANNER_SYSTEM_PROMPT = (
    "You are the Planner agent. Analyse requirements, outline steps, and delegate implementation tasks. "
    "Maintain the shared charter at context/TASK_CHARTER.md by recording goal, normalized target paths, "
    "acceptance criteria, and QA checklist. Replace any placeholder text such as 'Pending' before handing off. "
    "If you cannot supply concrete paths or criteria, escalate instead of writing a vague plan. Keep responses concise and structured."
)

IMPLEMENTER_SYSTEM_PROMPT = (
    "You are the Implementer agent. Apply code changes, run tools, and report concrete modifications. "
    "Read the shared charter before acting, and if it still contains placeholders (e.g., 'Pending') or ambiguous paths, "
    "send a status update back to the planner rather than guessing. When you do make changes, update the charter (or status note) "
    "with files touched, diffs produced, and verification performed so QA knows what to inspect. Prefer actionable commands over high-level discussion."
)

QA_SYSTEM_PROMPT = (
    "You are the QA agent. Validate that implementation satisfies the charter. Confirm each acceptance criterion, "
    "note any gaps back in the charter, and only give final approval when tests and manual checks pass. If the charter still "
    "contains placeholders or missing data, document the issue and route it back to planner/implementer instead of silently approving."
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
    module_file = src_dir / "text_utils.py"
    test_file = tests_dir / "test_text_utils.md"

    readme_content = (
        "# Live Agents Demo\n\n"
        "This mini-project contains a bug in `count_words` within `src/text_utils.py`.\n\n"
        "- Expected behavior: Return the number of words in a sentence regardless of extra whitespace or line breaks.\n"
        "- Bug: The current implementation splits only on single spaces, so multiple spaces or newlines inflate counts.\n\n"
        "Your task: plan, implement, and validate a robust fix.\n"
    )

    module_content = (
        "from __future__ import annotations\n\n"
        "def count_words(text: str) -> int:\n"
        "    \"\"\"Return the number of words in *text*.\n\n"
        "    Words should be separated by arbitrary whitespace (spaces, tabs, newlines).\n"
        "    BUG: The current implementation splits only on a single space character,\n"
        "    which produces empty tokens for consecutive spaces and ignores newlines.\n"
        "    \"\"\"\n"
        "    if not text:\n"
        "        return 0\n"
        "    # Deliberate bug: split on a single space, producing empty tokens\n"
        "    return len(text.split(" "))\n"
    )

    test_content = (
        "# Validation Notes for QA\n\n"
        "- `count_words(\"Hello world\")` should return 2.\n"
        "- Multiple spaces `count_words(\"One   two\")` should still return 2.\n"
        "- Newlines/tabs should be treated as separators.\n"
        "- Empty strings or strings with only whitespace should return 0.\n"
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
        project_root = Path(context_files[0]).parent  # projects/live_agents_demo
        module_path = project_root / "src" / "text_utils.py"
        readme_path = project_root / "README.md"
        charter_path = workspace / "context" / "TASK_CHARTER.md"
        charter_path.parent.mkdir(parents=True, exist_ok=True)

        project_rel_root = project_root.relative_to(workspace)
        module_rel_path = module_path.relative_to(workspace)
        readme_rel_path = readme_path.relative_to(workspace)
        charter_rel_path = charter_path.relative_to(workspace)

        base_charter = """# Task Charter

## Goal
- Fix `count_words` in `src/text_utils.py` so it handles arbitrary whitespace (spaces, tabs, newlines) and returns accurate counts, including 0 for empty/whitespace-only strings.

## Scope and Paths
- Workspace root: {root}
- Implementation file: {module}
- Tests: {tests}
- Documentation: {readme}

## Acceptance Criteria
- `count_words('Hello world') == 2`
- `count_words('One   two') == 2` (multiple spaces collapsed)
- `count_words('one\n two\tthree') == 3` (mixed whitespace)
- `count_words('   ') == 0` and `count_words('') == 0`
- Non-string inputs raise `TypeError`.
- Function docstring documents whitespace handling and error behaviour.

## QA Checklist
- Run `pytest {tests}`
- Manually spot-check the acceptance examples above.
- Confirm README summarises behaviour changes.

## Implementation Notes
- To be filled by the implementer after changes (files touched, verification performed).

## QA Verification
- To be completed by QA after validation (include pass/fail notes and evidence).
""".format(
            root=project_rel_root.as_posix(),
            module=module_rel_path.as_posix(),
            tests=f"{project_rel_root.as_posix()}/tests/test_text_utils.py",
            readme=readme_rel_path.as_posix(),
        )

        charter_path.write_text(base_charter, encoding="utf-8")

        print(f"Demo project base_dir: {project_root}")
        await client.load_context_files(context_files + [str(charter_path)])

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
                "In src/text_utils.py, count_words splits only on a single space which breaks when there are extra spaces or newlines. "
                "Outline a concise remediation plan with steps (planning only). "
                f"Write the key details (goal, normalized target paths, acceptance criteria, QA checklist) into {charter_rel_path.as_posix()} so other roles can rely on it. "
                f"Use workspace-relative paths such as {module_rel_path.as_posix()}, {readme_rel_path.as_posix()}, and {project_rel_root.as_posix()}/tests when updating the charter."
            ),
        )

        def charter_needs_revision(contents: str) -> bool:
            stripped = contents.strip()
            if not stripped:
                return True
            lowered = stripped.lower()
            if lowered in {"goal", "pending", "# task charter"}:
                return True
            return bool(re.search(r"\\bpending\\b|\\btodo\\b", contents.lower()))

        max_revision_attempts = 2
        for attempt in range(max_revision_attempts + 1):
            charter_contents = charter_path.read_text(encoding="utf-8")
            if not charter_needs_revision(charter_contents):
                break
            if attempt == max_revision_attempts:
                baseline_charter = f"""# Task Charter\n\n"""
                baseline_charter += "## Goal\n" \
                    "- Fix `count_words` in `src/text_utils.py` so it handles arbitrary whitespace and returns accurate counts.\\n\\n"
                baseline_charter += "## Scope and Paths\n" \
                    f"- Workspace root: {project_rel_root.as_posix()}\\n" \
                    f"- Implementation file: {module_rel_path.as_posix()}\\n" \
                    f"- Tests: {project_rel_root.as_posix()}/tests/test_text_utils.py\\n" \
                    f"- Documentation: {readme_rel_path.as_posix()}\\n\\n"
                baseline_charter += "## Acceptance Criteria\n" \
                    "- `count_words('Hello world') == 2`\\n" \
                    "- `count_words('One   two') == 2` (multiple spaces)\\n" \
                    "- `count_words('line1\\nline2') == 2` (newlines)\\n" \
                    "- `count_words('   ') == 0` (whitespace only)\\n" \
                    "- Non-string inputs raise `TypeError`.\\n" \
                    "- Function docstring documents whitespace handling and error behaviour.\\n\\n"
                baseline_charter += "## QA Checklist\n" \
                    f"- Run `pytest {project_rel_root.as_posix()}/tests/test_text_utils.py`\\n" \
                    "- Manually spot-check the acceptance criteria examples.\\n" \
                    "- Confirm README summarises behaviour.\\n\\n"
                baseline_charter += "## Implementation Notes\n- Pending\\n\\n"
                baseline_charter += "## QA Verification\n- Pending\\n"
                charter_path.write_text(baseline_charter, encoding="utf-8")
                await client.send_to_agent(
                    "planner",
                    "Baseline charter populated automatically; review and adjust if needed.",
                    channel=ROOM,
                    metadata={"from": "system"},
                )
                break
            await chat(
                client,
                "planner",
                (
                    f"The charter at {charter_rel_path.as_posix()} still contains placeholders (e.g., 'Pending') or is incomplete. "
                    "Replace the template with concrete details: list the goal, scope, normalized paths, acceptance criteria, QA checklist, and any planned tests. "
                    "Use apply_diff to update each section so implementer and QA have actionable guidance."
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
                "Goal: ensure count_words handles arbitrary whitespace (spaces, tabs, newlines, leading/trailing whitespace) and returns 0 for empty/whitespace-only strings.\n\n"
                "Steps:\n"
                f"1) Read the file (use <enhanced_read>{module_rel_path.as_posix()}:true:400</enhanced_read>).\n"
                "2) Apply a minimal diff so word counting handles arbitrary whitespace (e.g., multiple spaces, tabs, newlines) and update the docstring with the new behavior.\n"
                f"3) Update or create lightweight tests (e.g., {project_rel_root.as_posix()}/tests/test_text_utils.py) to cover multiple spaces, newlines, and empty strings, and refresh the README note ({readme_rel_path.as_posix()}) if helpful.\n\n"
                f"Consult {charter_rel_path.as_posix()} before acting. If the charter still contains placeholders (e.g., 'Pending') or unclear paths, send a status message back to the planner instead of editing.\n"
                f"When you do make changes, append a short summary of files changed plus verification steps under 'Implementation Notes' in {charter_rel_path.as_posix()} using apply_diff.\n\n"
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
                "Validate that count_words handles arbitrary whitespace correctly (single/multiple spaces, tabs, newlines, leading/trailing whitespace) and that empty strings return 0. "
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
