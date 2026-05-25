"""Core shim coverage for extracted agent lifecycle helpers."""

from __future__ import annotations

from typing import Any

from penguin.core import PenguinCore


def test_core_agent_lifecycle_shims_delegate_to_runtime(monkeypatch) -> None:
    core = PenguinCore.__new__(PenguinCore)
    calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def _ensure(*args: Any, **kwargs: Any) -> None:
        calls.append(("ensure", args, kwargs))

    def _create(*args: Any, **kwargs: Any) -> None:
        calls.append(("create", args, kwargs))

    def _delete(*args: Any, **kwargs: Any) -> bool:
        calls.append(("delete", args, kwargs))
        return True

    def _delete_guarded(*args: Any, **kwargs: Any) -> dict[str, Any]:
        calls.append(("delete_guarded", args, kwargs))
        return {"success": True, "warning": None}

    def _persona_catalog(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        calls.append(("persona_catalog", args, kwargs))
        return [{"id": "persona"}]

    def _roster(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        calls.append(("roster", args, kwargs))
        return [{"id": "worker"}]

    def _profile(*args: Any, **kwargs: Any) -> dict[str, Any]:
        calls.append(("profile", args, kwargs))
        return {"id": args[1]}

    def _unregister(*args: Any, **kwargs: Any) -> bool:
        calls.append(("unregister", args, kwargs))
        return False

    monkeypatch.setattr(
        "penguin.core.core_agent_lifecycle.get_persona_catalog",
        _persona_catalog,
    )
    monkeypatch.setattr(
        "penguin.core.core_agent_lifecycle.get_agent_roster",
        _roster,
    )
    monkeypatch.setattr(
        "penguin.core.core_agent_lifecycle.get_agent_profile",
        _profile,
    )
    monkeypatch.setattr(
        "penguin.core.core_agent_lifecycle.ensure_agent_conversation",
        _ensure,
    )
    monkeypatch.setattr(
        "penguin.core.core_agent_lifecycle.create_sub_agent",
        _create,
    )
    monkeypatch.setattr(
        "penguin.core.core_agent_lifecycle.delete_agent_conversation",
        _delete,
    )
    monkeypatch.setattr(
        "penguin.core.core_agent_lifecycle.delete_agent_conversation_guarded",
        _delete_guarded,
    )
    monkeypatch.setattr(
        "penguin.core.core_agent_lifecycle.unregister_agent",
        _unregister,
    )

    assert core.get_persona_catalog() == [{"id": "persona"}]
    assert core.get_agent_roster() == [{"id": "worker"}]
    assert core.get_agent_profile("worker") == {"id": "worker"}
    core.ensure_agent_conversation("worker", system_prompt="system", legacy=True)
    core.create_sub_agent(
        "child",
        parent_agent_id="worker",
        system_prompt="child-system",
        share_session=False,
    )
    assert core.delete_agent_conversation_guarded("worker", "conv_1") == {
        "success": True,
        "warning": None,
    }
    assert core.delete_agent_conversation("worker") is True
    assert core.unregister_agent("worker", preserve_conversation=True) is False

    assert calls == [
        ("persona_catalog", (core,), {}),
        ("roster", (core,), {}),
        ("profile", (core, "worker"), {}),
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
            "delete_guarded",
            (core, "worker", "conv_1"),
            {"force": False},
        ),
        ("delete", (core, "worker"), {}),
        ("unregister", (core, "worker"), {"preserve_conversation": True}),
    ]
