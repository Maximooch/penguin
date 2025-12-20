"""Phase 0 interactive multi-agent scenario simulation.

This script orchestrates a deterministic, multi-agent conversation that mirrors
how a real Penguin session might coordinate between personas.  It uses the
same stub infrastructure as the other Phase 0 checks so it can run quickly and
without network access while still exercising ``PenguinCore.process``.

Run with:

    uv run python scripts/phase0_interactive_example.py

Scenario summary:
    * Planner agent outlines the approach for fixing a failing function.
    * Implementer agent produces the patch.
    * QA sub-agent verifies behaviour with targeted tests.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional
from unittest.mock import AsyncMock, MagicMock

from penguin.core import PenguinCore
from penguin.system.state import MessageCategory


# ---------------------------------------------------------------------------
# Scenario definition
# ---------------------------------------------------------------------------


SCENARIO = {
    "title": "Phase 0 Example – Fixing empty-input bug",
    "description": (
        "Coordinate planner, implementer, and QA personas to address a function "
        "that crashes when given an empty list."
    ),
    "conversation_id": "bugfix-empty-input",
    "steps": [
        {
            "agent": "planner",
            "prompt": "We discovered that summarize_numbers([]) raises a ValueError. "
            "Draft a remediation plan.",
            "response": (
                "Plan:\n1. Update summarize_numbers to short-circuit empty input.\n"
                "2. Add regression test covering the empty list case.\n"
                "3. Verify existing aggregation behaviour remains unchanged."
            ),
        },
        {
            "agent": "implementer",
            "prompt": (
                "Apply the plan: modify summarize_numbers and include a regression test."
            ),
            "response": (
                "Patch applied. summarize_numbers now returns {'count': 0, 'total': 0, 'average': 0}. "
                "Added test `test_empty_input_returns_zeroes` covering the regression."
            ),
        },
        {
            "agent": "qa",
            "prompt": (
                "Validate the new behaviour and ensure standard datasets still pass."
            ),
            "response": (
                "QA summary: regression test passes; legacy dataset checks remain green. "
                "No further issues detected."
            ),
        },
    ],
}


# ---------------------------------------------------------------------------
# Stub infrastructure (conversation manager, engine, core helper)
# ---------------------------------------------------------------------------


@dataclass
class StubMessage:
    role: str
    content: Any
    category: MessageCategory
    metadata: Dict[str, Any]
    agent_id: Optional[str]


@dataclass
class StubSession:
    id: str
    messages: List[StubMessage] = field(default_factory=list)


class StubConversation:
    def __init__(self, agent_id: str) -> None:
        self.agent_id = agent_id
        self.prepared: List[Any] = []
        self.session = StubSession(id=f"session-{agent_id}")

    def prepare_conversation(self, message: str, image_path: Optional[str] = None) -> None:
        self.prepared.append((message, image_path))


class ScenarioConversationManager:
    def __init__(self) -> None:
        self.current_agent_id = "default"
        self.agent_sessions: Dict[str, StubConversation] = {}
        self.loaded: List[tuple[str, str]] = []
        self.loaded_files: List[tuple[str, str]] = []
        self.saved = False
        self._ensure_agent("default")
        self.conversation: StubConversation = self.agent_sessions["default"]

    def _ensure_agent(self, agent_id: str) -> None:
        if agent_id not in self.agent_sessions:
            self.agent_sessions[agent_id] = StubConversation(agent_id)

    def set_current_agent(self, agent_id: str) -> None:
        self.current_agent_id = agent_id
        self._ensure_agent(agent_id)
        self.conversation = self.agent_sessions[agent_id]

    def load(self, conversation_id: str) -> bool:
        self._ensure_agent(self.current_agent_id)
        self.loaded.append((self.current_agent_id, conversation_id))
        return True

    def load_context_file(self, path: str) -> None:
        self.loaded_files.append((self.current_agent_id, path))

    def save(self) -> None:
        self.saved = True

    def get_token_usage(self) -> Dict[str, Dict[str, int]]:
        return {"total": {"input": 0, "output": 0}, "session": {"input": 0, "output": 0}}

    def get_current_session(self) -> Optional[StubSession]:
        return self.conversation.session


class ScenarioEngine:
    def __init__(self, conversation_manager: ScenarioConversationManager, steps: Iterable[Dict[str, Any]]) -> None:
        self._conversation_manager = conversation_manager
        self._steps = iter(steps)

        async def _step(prompt: str, *, agent_id: Optional[str] = None, **_: Any) -> Dict[str, Any]:
            try:
                step = next(self._steps)
            except StopIteration as exc:
                raise AssertionError("No scenario steps remaining") from exc

            assert step["agent"] == agent_id, f"Expected agent {step['agent']}, got {agent_id}"
            assert step["prompt"] == prompt, f"Unexpected prompt for agent {agent_id}: {prompt}"

            conv = self._conversation_manager.conversation
            conv.session.messages.append(
                StubMessage(
                    role="assistant",
                    content=step["response"],
                    category=MessageCategory.DIALOG,
                    metadata={"scenario_step": step["agent"]},
                    agent_id=agent_id,
                )
            )
            return {"assistant_response": step["response"], "action_results": []}

        self.run_single_turn = AsyncMock(side_effect=_step)


def _build_core(cm: ScenarioConversationManager, engine: ScenarioEngine) -> PenguinCore:
    core = PenguinCore.__new__(PenguinCore)
    core.conversation_manager = cm
    core.engine = engine
    core.emit_ui_event = AsyncMock()
    core._handle_stream_chunk = AsyncMock()
    # Mock StreamingStateManager for streaming property accessors
    stream_mgr = MagicMock()
    stream_mgr.is_active = False
    stream_mgr.content = ""
    stream_mgr.reasoning_content = ""
    stream_mgr.stream_id = None
    core._stream_manager = stream_mgr
    core.event_types = {"message"}
    core._interrupted = False
    return core


# ---------------------------------------------------------------------------
# Scenario runner
# ---------------------------------------------------------------------------


async def run_interactive_scenario() -> None:
    cm = ScenarioConversationManager()
    engine = ScenarioEngine(cm, SCENARIO["steps"])
    core = _build_core(cm, engine)

    transcript: List[Dict[str, Any]] = []
    conversation_id = SCENARIO["conversation_id"]

    print(f"\n=== {SCENARIO['title']} ===")
    print(SCENARIO["description"])

    for idx, step in enumerate(SCENARIO["steps"], start=1):
        print(f"\nStep {idx}: {step['agent']} → core.process()")
        print(f"Prompt: {step['prompt']}")
        result = await core.process(
            input_data={"text": step["prompt"]},
            agent_id=step["agent"],
            conversation_id=conversation_id,
            streaming=False,
            multi_step=False,
        )
        response = result["assistant_response"]
        print(f"Response: {response}")
        transcript.append({
            "agent": step["agent"],
            "prompt": step["prompt"],
            "response": response,
        })

    print("\n=== Scenario transcript (summary) ===")
    for entry in transcript:
        print(f"[{entry['agent']}]\n  prompt: {entry['prompt']}\n  response: {entry['response']}\n")


if __name__ == "__main__":
    asyncio.run(run_interactive_scenario())
