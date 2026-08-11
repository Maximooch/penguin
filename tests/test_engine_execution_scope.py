"""Engine request-scope invariants."""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast
from unittest.mock import MagicMock

import pytest

from penguin.engine import Engine, EngineSettings
from penguin.skills.manager import SkillManager
from penguin.skills.models import Skill
from penguin.system.execution_context import ExecutionContext, execution_context_scope

if TYPE_CHECKING:
    from pathlib import Path


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
        cast("Any", base_manager),
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
        cast("Any", _conversation_manager("session_requested_by_tui")),
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


@pytest.mark.asyncio
async def test_trusted_request_agent_missing_from_registry_fails_closed() -> None:
    engine = Engine(
        EngineSettings(),
        cast("Any", _conversation_manager("telegram-session")),
        MagicMock(),
        MagicMock(),
        MagicMock(),
    )

    with execution_context_scope(
        ExecutionContext(
            session_id="telegram-session",
            agent_id="configured-agent",
            require_registered_agent=True,
        )
    ):
        with pytest.raises(ValueError, match="unavailable: configured-agent"):
            await engine._resolve_agent(
                agent_id="configured-agent",
                agent_role=None,
                prompt="Use the configured Telegram agent.",
            )


def test_request_prompt_and_skills_are_ephemeral_system_messages(
    tmp_path: Path,
) -> None:
    skill_root = tmp_path / "skills" / "focused-work"
    skill_root.mkdir(parents=True)
    skill_file = skill_root / "SKILL.md"
    skill_file.write_text("unused", encoding="utf-8")
    skill = Skill(
        name="focused-work",
        description="Stay focused.",
        path=skill_root,
        skill_file=skill_file,
        body="Use the smallest complete solution.",
        source="test",
    )
    skill_manager = SkillManager.__new__(SkillManager)
    skill_manager._skills = {skill.name: skill}
    skill_manager._diagnostics = []
    skill_manager._activated_by_session = {}

    conversation_manager = _conversation_manager("telegram-session")
    conversation_manager.skill_manager = skill_manager
    engine = Engine(
        EngineSettings(),
        cast("Any", conversation_manager),
        MagicMock(),
        MagicMock(),
        MagicMock(),
    )
    messages = [{"role": "user", "content": "hello"}]

    with execution_context_scope(
        ExecutionContext(
            session_id="telegram-session",
            agent_id="default",
            agent_mode="plan",
            request_system_prompt="Answer for the operations team.",
            request_skills=("focused-work",),
        )
    ):
        scoped = engine._apply_agent_mode_notice(messages)
        repeated = engine._apply_agent_mode_notice(scoped)

    assert scoped is not messages
    assert [message["role"] for message in scoped] == [
        "user",
        "system",
        "system",
        "system",
    ]
    assert "[PENGUIN_AGENT_MODE_PLAN]" in scoped[1]["content"]
    assert "[PENGUIN_TRUSTED_REQUEST_PROMPT]" in scoped[2]["content"]
    assert "Answer for the operations team." in scoped[2]["content"]
    assert "[PENGUIN_REQUEST_SKILL:focused-work]" in scoped[3]["content"]
    assert "Use the smallest complete solution." in scoped[3]["content"]
    assert repeated == scoped
    assert conversation_manager.conversation.session.messages == []
    assert skill_manager.active_names("telegram-session") == []
    assert engine._apply_agent_mode_notice(messages) is messages


def test_request_skill_missing_from_trusted_catalog_fails_closed() -> None:
    conversation_manager = _conversation_manager("telegram-session")
    conversation_manager.skill_manager = SimpleNamespace(get=lambda _name: None)
    engine = Engine(
        EngineSettings(),
        cast("Any", conversation_manager),
        MagicMock(),
        MagicMock(),
        MagicMock(),
    )

    with execution_context_scope(
        ExecutionContext(
            session_id="telegram-session",
            agent_id="default",
            request_skills=("missing-skill",),
        )
    ):
        with pytest.raises(ValueError, match="unavailable: missing-skill"):
            engine._apply_agent_mode_notice([{"role": "user", "content": "hello"}])
