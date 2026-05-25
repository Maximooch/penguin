"""Core shim coverage for extracted session lookup helpers."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from penguin.core import PenguinCore
from penguin.core_runtime import session_lookup


class _Manager:
    def __init__(self, sessions: dict[str, Any]) -> None:
        self.sessions = sessions
        self.session_index: dict[str, dict[str, Any]] = {}


def test_core_find_session_store_shim_matches_runtime_helper() -> None:
    session = SimpleNamespace(id="session_agent")
    default_manager = _Manager({})
    agent_manager = _Manager({"session_agent": (session, False)})
    core = PenguinCore.__new__(PenguinCore)
    core.conversation_manager = SimpleNamespace(
        session_manager=default_manager,
        agent_session_managers={"build": agent_manager},
    )

    shim_result = core._find_session_store("session_agent")
    helper_result = session_lookup.find_session_store(core, "session_agent")

    assert shim_result == helper_result
    assert shim_result == (session, agent_manager)
