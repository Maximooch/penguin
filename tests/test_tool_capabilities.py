from __future__ import annotations

import json

import pytest

from penguin.tools.tool_manager import ToolManager

ENV_NAME = "PENGUIN_TOOL_ALLOWLIST_JSON"


def _manager(monkeypatch: pytest.MonkeyPatch, value: str | None) -> ToolManager:
    if value is None:
        monkeypatch.delenv(ENV_NAME, raising=False)
    else:
        monkeypatch.setenv(ENV_NAME, value)
    return ToolManager({}, lambda *_args, **_kwargs: None, fast_startup=True)


def _payload(result: object) -> dict[str, object]:
    assert isinstance(result, str)
    return json.loads(result)


def test_unset_policy_is_unrestricted(monkeypatch: pytest.MonkeyPatch) -> None:
    manager = _manager(monkeypatch, None)

    assert manager.tool_capability_policy.restricted is False
    assert "read_file" in {tool["name"] for tool in manager.get_tools()}


def test_sync_dispatch_denies_tool_before_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _manager(monkeypatch, '["read_file"]')

    payload = _payload(
        manager.execute_tool("execute_command", {"command": "printf secret-value"})
    )

    assert payload == {
        "error": "tool_capability_denied",
        "tool": "execute_command",
        "reason": "Tool is not enabled by the startup capability policy.",
    }
    assert "secret-value" not in json.dumps(payload)


@pytest.mark.asyncio
async def test_async_native_dispatch_denies_subagent_even_when_context_enables_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _manager(monkeypatch, '["read_file"]')

    payload = _payload(
        await manager.execute_tool_async(
            "spawn_sub_agent",
            {"id": "blocked", "initial_prompt": "do not disclose"},
            context={"subagents_enabled": True},
        )
    )

    assert payload["error"] == "tool_capability_denied"
    assert payload["tool"] == "spawn_sub_agent"
    assert "do not disclose" not in json.dumps(payload)


def test_alias_requires_canonical_name_in_allowlist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    alias_only = _manager(monkeypatch, '["enhanced_read"]')
    denied = _payload(alias_only.execute_tool("enhanced_read", {"path": "missing"}))
    assert denied["error"] == "tool_capability_denied"
    assert denied["tool"] == "enhanced_read"

    canonical = _manager(monkeypatch, '["read_file"]')
    assert canonical.tool_capability_policy.allows(
        "enhanced_read", canonical._canonical_tool_name("enhanced_read")
    )


def test_ordered_batch_parent_and_children_are_independently_enforced(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    child_only = _manager(monkeypatch, '["read_file"]')
    parent_denied = _payload(
        child_only.execute_tool("ordered_tool_batch", {"tool_uses": []})
    )
    assert parent_denied["error"] == "tool_capability_denied"
    assert parent_denied["tool"] == "ordered_tool_batch"

    parent_only = _manager(monkeypatch, '["ordered_tool_batch"]')
    result = _payload(
        parent_only.execute_tool(
            "ordered_tool_batch",
            {"tool_uses": [{"tool": "read_file", "arguments": {"path": "missing"}}]},
        )
    )
    assert result["status"] == "error"
    assert "tool_capability_denied" in json.dumps(result)


def test_get_tools_filters_to_startup_allowlist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _manager(monkeypatch, '["read_file"]')

    assert {tool["name"] for tool in manager.get_tools()} == {"read_file"}
    assert {tool["name"] for tool in manager.get_model_visible_tools()} == {"read_file"}
    assert {tool.get("name") for tool in manager.get_responses_tools()} == {"read_file"}


def test_allowlisted_mcp_tool_is_exposed_and_dispatched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _manager(monkeypatch, '["private_proxy"]')
    monkeypatch.setattr(
        manager._mcp_provider,
        "get_tool_schemas",
        lambda: [
            {
                "name": "private_proxy",
                "description": "Private backend proxy",
                "input_schema": {"type": "object", "properties": {}},
            }
        ],
    )
    monkeypatch.setattr(
        manager._mcp_provider,
        "is_mcp_tool",
        lambda name: name == "private_proxy",
    )
    monkeypatch.setattr(
        manager._mcp_provider,
        "execute_tool",
        lambda name, arguments: {"name": name, "arguments": arguments},
    )

    assert {tool["name"] for tool in manager.get_tools()} == {"private_proxy"}
    assert manager.execute_tool("private_proxy", {"record_id": "safe"}) == {
        "name": "private_proxy",
        "arguments": {"record_id": "safe"},
    }


@pytest.mark.parametrize("value", ["", "not-json", "{}", "[]", '["", 3]'])
def test_malformed_or_empty_policy_fails_closed(
    monkeypatch: pytest.MonkeyPatch, value: str
) -> None:
    manager = _manager(monkeypatch, value)

    assert manager.tool_capability_policy.restricted is True
    assert manager.get_tools() == []
    payload = _payload(manager.execute_tool("read_file", {"path": "anything"}))
    assert payload["error"] == "tool_capability_denied"


def test_policy_is_immutable_for_manager_lifetime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _manager(monkeypatch, '["read_file"]')
    monkeypatch.setenv(ENV_NAME, '["execute_command"]')
    manager.config["tool_allowlist"] = ["execute_command"]

    assert manager.tool_capability_policy.allowed_names == frozenset({"read_file"})
    payload = _payload(manager.execute_tool("execute_command", {"command": "true"}))
    assert payload["error"] == "tool_capability_denied"


def test_get_tool_cannot_bypass_capability_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager = _manager(monkeypatch, '["read_file"]')

    with pytest.raises(PermissionError, match="tool_capability_denied"):
        manager.get_tool("execute_command")
