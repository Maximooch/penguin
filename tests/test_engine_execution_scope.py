"""Engine request-scope invariants."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import MagicMock

import pytest

from penguin.engine import Engine, EngineSettings
from penguin.system.execution_context import ExecutionContext, execution_context_scope


def _conversation_manager(session_id: str) -> Any:
    """Build a minimal conversation manager with a stable session."""

    session = SimpleNamespace(id=session_id, messages=[])
    conversation = SimpleNamespace(
        session=session,
        save=MagicMock(return_value=True),
        add_action_result=MagicMock(),
    )
    return SimpleNamespace(
        core=None,
        conversation=conversation,
        get_agent_conversation=MagicMock(return_value=conversation),
        save=MagicMock(return_value=True),
        get_current_session=MagicMock(return_value=session),
        agent_context_windows={},
    )


def test_plain_preloaded_manager_is_stable_for_the_entire_engine_run() -> None:
    """Repeated component resolution must retain the request-loaded session."""

    base_manager = _conversation_manager("session_nested_agent")
    request_manager = _conversation_manager("session_requested_by_tui")
    engine = Engine(
        EngineSettings(),
        cast(Any, base_manager),
        MagicMock(),
        MagicMock(),
        MagicMock(),
    )

    with execution_context_scope(
        ExecutionContext(
            session_id="session_requested_by_tui",
            conversation_id="session_requested_by_tui",
            agent_id="default",
            request_id="request_scope_regression",
        )
    ):
        engine.prime_scoped_conversation_manager("default", request_manager)
        with engine._run_state_scope("default"):
            first = engine.get_conversation_manager("default")
            second = engine.get_conversation_manager("default")

    assert first is request_manager
    assert second is request_manager
    assert second.get_current_session().id == "session_requested_by_tui"


@pytest.mark.asyncio
async def test_unknown_requested_agent_normalizes_to_default() -> None:
    """A degraded TUI agent label must not create an implicit child session."""

    engine = Engine(
        EngineSettings(),
        cast(Any, _conversation_manager("session_requested_by_tui")),
        MagicMock(),
        MagicMock(),
        MagicMock(),
    )

    resolved_agent, lite_result = await engine._resolve_agent(
        agent_id="penguin",
        agent_role=None,
        prompt="Continue the selected session.",
    )

    assert resolved_agent == "default"
    assert lite_result is None
    assert engine.list_agents() == ["default"]
