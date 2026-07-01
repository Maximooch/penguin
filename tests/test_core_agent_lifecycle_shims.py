"""Core shim coverage for extracted agent lifecycle helpers."""

from __future__ import annotations

import asyncio
from typing import Any

from penguin.core import PenguinCore


def test_core_agent_lifecycle_shims_delegate_to_runtime(monkeypatch) -> None:
    core = PenguinCore.__new__(PenguinCore)
    calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
    facade_globals = PenguinCore.get_persona_catalog.__globals__
    agent_lifecycle = facade_globals["core_agent_lifecycle"]

    def record(name: str, result: Any = None):
        def _inner(*args: Any, **kwargs: Any) -> Any:
            calls.append((name, args, kwargs))
            return result

        return _inner

    def record_async(name: str, result: Any = None):
        async def _inner(*args: Any, **kwargs: Any) -> Any:
            calls.append((name, args, kwargs))
            return result

        return _inner

    def _profile(*args: Any, **kwargs: Any) -> dict[str, Any]:
        calls.append(("profile", args, kwargs))
        return {"id": args[1]}

    monkeypatch.setattr(
        agent_lifecycle,
        "get_persona_catalog",
        record("persona_catalog", [{"id": "persona"}]),
    )
    monkeypatch.setattr(
        agent_lifecycle,
        "get_agent_roster",
        record("roster", [{"id": "worker"}]),
    )
    monkeypatch.setattr(agent_lifecycle, "get_agent_profile", _profile)
    monkeypatch.setattr(
        agent_lifecycle,
        "register_agent_compat",
        record("register_agent_compat"),
    )
    monkeypatch.setattr(
        agent_lifecycle,
        "set_active_agent",
        record("set_active_agent"),
    )
    monkeypatch.setattr(
        agent_lifecycle,
        "create_agent_conversation",
        record("create_conversation", "conv_worker"),
    )
    monkeypatch.setattr(
        agent_lifecycle,
        "list_agent_conversations",
        record("list_conversations", [{"id": "conv_worker"}]),
    )
    monkeypatch.setattr(
        agent_lifecycle,
        "load_agent_conversation",
        record("load_conversation", True),
    )
    monkeypatch.setattr(
        agent_lifecycle,
        "list_agents",
        record("list_agents", ["default", "worker"]),
    )
    monkeypatch.setattr(
        agent_lifecycle,
        "list_sub_agents",
        record("list_sub_agents", {"default": ["worker"]}),
    )
    monkeypatch.setattr(
        agent_lifecycle,
        "set_agent_paused",
        record("set_agent_paused"),
    )
    monkeypatch.setattr(
        agent_lifecycle,
        "is_agent_paused",
        record("is_agent_paused", False),
    )
    monkeypatch.setattr(
        agent_lifecycle,
        "ensure_agent_conversation",
        record("ensure"),
    )
    monkeypatch.setattr(
        agent_lifecycle,
        "create_sub_agent",
        record("create"),
    )
    monkeypatch.setattr(
        agent_lifecycle,
        "publish_sub_agent_session_created",
        record_async("publish_sub_agent_session_created", {"session_id": "child"}),
    )
    monkeypatch.setattr(
        agent_lifecycle,
        "resolve_agent_execution_scope",
        record(
            "resolve_agent_execution_scope",
            {
                "session_id": "session_child",
                "directory": "/tmp/work",
                "agent_mode": "isolated",
            },
        ),
    )
    monkeypatch.setattr(
        agent_lifecycle,
        "run_agent_prompt_in_session",
        record_async("run_agent_prompt_in_session", {"response": "done"}),
    )
    monkeypatch.setattr(
        agent_lifecycle,
        "delete_agent_conversation_compat",
        record("delete_compat", True),
    )
    monkeypatch.setattr(
        agent_lifecycle,
        "delete_agent_conversation_guarded",
        record("delete_guarded", {"success": True, "warning": None}),
    )
    monkeypatch.setattr(
        agent_lifecycle,
        "unregister_agent",
        record("unregister", False),
    )

    assert core.get_persona_catalog() == [{"id": "persona"}]
    assert core.get_agent_roster() == [{"id": "worker"}]
    assert core.get_agent_profile("worker") == {"id": "worker"}
    core.register_agent("legacy", persona="research")
    core.set_active_agent("worker")
    assert core.create_agent_conversation("worker") == "conv_worker"
    assert core.list_all_conversations(limit_per_agent=3, offset=1) == [
        {"id": "conv_worker"}
    ]
    assert core.load_agent_conversation("worker", "conv_worker", activate=False) is True
    assert core.list_agents() == ["default", "worker"]
    assert core.list_sub_agents("default") == {"default": ["worker"]}
    core.set_agent_paused("worker", paused=False)
    assert core.is_agent_paused("worker") is False
    core.ensure_agent_conversation("worker", system_prompt="system", legacy=True)
    core.create_sub_agent(
        "child",
        parent_agent_id="worker",
        system_prompt="child-system",
        share_session=False,
    )
    assert asyncio.run(
        core.publish_sub_agent_session_created(
            "child",
            parent_agent_id="worker",
            share_session=False,
        )
    ) == {"session_id": "child"}
    assert core.resolve_agent_execution_scope(
        "child",
        session_id="session_child",
        directory="/tmp/work",
        agent_mode="isolated",
    ) == {
        "session_id": "session_child",
        "directory": "/tmp/work",
        "agent_mode": "isolated",
    }
    assert asyncio.run(
        core.run_agent_prompt_in_session(
            "child",
            "hello",
            session_id="session_child",
            directory="/tmp/work",
            agent_mode="isolated",
            streaming=True,
        )
    ) == {"response": "done"}
    assert core.delete_agent_conversation_guarded("worker", "conv_1") == {
        "success": True,
        "warning": None,
    }
    assert core.delete_agent_conversation("worker") is True
    assert core.delete_agent_conversation("worker", "conv_1") is True
    assert core.unregister_agent("worker", preserve_conversation=True) is False

    assert calls == [
        ("persona_catalog", (core,), {}),
        ("roster", (core,), {}),
        ("profile", (core, "worker"), {}),
        ("register_agent_compat", (core, "legacy"), {"persona": "research"}),
        ("set_active_agent", (core, "worker"), {}),
        ("create_conversation", (core, "worker"), {}),
        (
            "list_conversations",
            (core,),
            {"limit_per_agent": 3, "offset": 1},
        ),
        (
            "load_conversation",
            (core, "worker", "conv_worker"),
            {"activate": False},
        ),
        ("list_agents", (core,), {}),
        ("list_sub_agents", (core, "default"), {}),
        ("set_agent_paused", (core, "worker", False), {}),
        ("is_agent_paused", (core, "worker"), {}),
        (
            "ensure",
            (core, "worker"),
            {"system_prompt": "system"},
        ),
        (
            "create",
            (core, "child"),
            {
                "parent_agent_id": "worker",
                "system_prompt": "child-system",
                "share_session": False,
                "share_context_window": True,
                "shared_context_window_max_tokens": None,
            },
        ),
        (
            "publish_sub_agent_session_created",
            (core, "child"),
            {"parent_agent_id": "worker", "share_session": False},
        ),
        (
            "resolve_agent_execution_scope",
            (core, "child"),
            {
                "session_id": "session_child",
                "directory": "/tmp/work",
                "agent_mode": "isolated",
            },
        ),
        (
            "run_agent_prompt_in_session",
            (core, "child", "hello"),
            {
                "session_id": "session_child",
                "directory": "/tmp/work",
                "agent_mode": "isolated",
                "streaming": True,
            },
        ),
        (
            "delete_guarded",
            (core, "worker", "conv_1"),
            {"force": False},
        ),
        ("delete_compat", (core, "worker", None), {}),
        ("delete_compat", (core, "worker", "conv_1"), {}),
        ("unregister", (core, "worker"), {"preserve_conversation": True}),
    ]


def test_core_agent_routing_shims_delegate_to_multi_runtime(monkeypatch) -> None:
    core = PenguinCore.__new__(PenguinCore)
    calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
    facade_globals = PenguinCore.route_message.__globals__
    multi_routing = facade_globals["multi_routing"]
    expected_logger = facade_globals["logger"]

    def record_async(name: str):
        async def _inner(*args: Any, **kwargs: Any) -> bool:
            calls.append((name, args, kwargs))
            return True

        return _inner

    monkeypatch.setattr(multi_routing, "route_message", record_async("route_message"))
    monkeypatch.setattr(multi_routing, "send_to_agent", record_async("send_to_agent"))
    monkeypatch.setattr(multi_routing, "send_to_human", record_async("send_to_human"))
    monkeypatch.setattr(multi_routing, "human_reply", record_async("human_reply"))

    async def run() -> None:
        assert await core.route_message(
            "worker",
            {"task": "build"},
            message_type="task",
            metadata={"priority": "high"},
            agent_id="planner",
            channel="agent",
        )
        assert await core.send_to_agent(
            "worker",
            "ping",
            message_type="direct",
            metadata={"m": 1},
            channel="agent",
        )
        assert await core.send_to_human(
            "status",
            message_type="status",
            metadata={"m": 2},
            channel="ui",
        )
        assert await core.human_reply(
            "worker",
            "ack",
            message_type="reply",
            metadata={"m": 3},
            channel="agent",
        )

    asyncio.run(run())

    assert calls == [
        (
            "route_message",
            (core, "worker", {"task": "build"}),
            {
                "message_type": "task",
                "metadata": {"priority": "high"},
                "agent_id": "planner",
                "channel": "agent",
                "logger": expected_logger,
            },
        ),
        (
            "send_to_agent",
            (core, "worker", "ping"),
            {"message_type": "direct", "metadata": {"m": 1}, "channel": "agent"},
        ),
        (
            "send_to_human",
            (core, "status"),
            {"message_type": "status", "metadata": {"m": 2}, "channel": "ui"},
        ),
        (
            "human_reply",
            (core, "worker", "ack"),
            {"message_type": "reply", "metadata": {"m": 3}, "channel": "agent"},
        ),
    ]
