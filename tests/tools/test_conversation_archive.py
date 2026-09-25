"""View-only archive lookup, tool exposure, and boundary tests."""

import json
import logging
import os
from pathlib import Path

import pytest

from penguin.security.permission_engine import Operation, PermissionResult, PolicyEngine
from penguin.security.tool_permissions import extract_resources_from_input, get_tool_operations
from penguin.tools.core import conversation_archive
from penguin.tools.core.conversation_archive import _MAX_SESSION_BYTES, open_session, search
from penguin.tools.tool_manager import ToolManager


def _session(root: Path, name: str, text: str, *, agent: str | None = None) -> Path:
    folder = root / "conversations" / agent if agent else root / "conversations"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{name}.json"
    path.write_text(json.dumps({
        "id": name,
        "created_at": "2025-01-01",
        "metadata": {"title": "A conversation"},
        "messages": [
            {"id": "sys", "role": "system", "category": "SYSTEM", "content": "secret needle"},
            {"id": "u1", "role": "user", "category": "DIALOG", "content": text},
            {"id": "a1", "role": "assistant", "category": "DIALOG", "content": "The answer is yes"},
        ],
    }))
    return path


def test_find_and_open_archive_without_writes(tmp_path):
    root = tmp_path / "workspace"
    primary = _session(root, "old", "We discussed 7k lines then 30k")
    other = _session(root, "child", "7k lines in a subagent", agent="researcher")
    before = [(p.read_bytes(), p.stat().st_mtime_ns) for p in (primary, other)]

    results = search(root, "7K")
    assert {(r["session_id"], r["agent_id"], r["message_index"]) for r in results["results"]} == {
        ("old", None, 1), ("child", "researcher", 1),
    }
    assert search(root, "7K", case_sensitive=True)["results"] == []
    assert search(root, "secret needle")["results"] == []
    assert [r["session_id"] for r in search(root, "7k", agent_id="researcher")["results"]] == ["child"]
    opened = open_session(root, "old", message_start=1, limit=1)
    assert opened["total_messages"] == 3
    assert opened["messages"][0]["content"] == "We discussed 7k lines then 30k"
    assert opened["messages"][0]["message_index"] == 1
    assert opened["path"] == str(primary)
    assert [(p.read_bytes(), p.stat().st_mtime_ns) for p in (primary, other)] == before


def test_archive_boundaries_and_ambiguity(tmp_path):
    root = tmp_path / "workspace"
    _session(root, "same", "hello")
    _session(root, "same", "hello child", agent="researcher")
    outside = _session(tmp_path / "outside", "private", "hello")
    (root / "conversations" / "linked.json").symlink_to(outside)
    (root / "conversations" / "external").symlink_to(outside.parent)
    (root / "conversations" / "session_index.json").write_text('{"password": "hello"}')
    assert len(search(root, "hello")["results"]) == 2
    assert open_session(root, "linked")["error"] == "session_not_found"
    assert open_session(root, "same")["error"] == "ambiguous_session_id"
    assert open_session(root, "same", agent_id="researcher")["agent_id"] == "researcher"
    for bad in ("../outside/private", ".."):
        with pytest.raises(ValueError):
            open_session(root, "same", agent_id=bad)
    with pytest.raises(ValueError):
        open_session(root, "../private")
    assert search(root, "hello", agent_id="external")["results"] == []
    assert open_session(root, "missing")["error"] == "session_not_found"
    assert open_session(root, "same", agent_id="")["error"] == "ambiguous_session_id"
    assert len(search(root, "hello", agent_id="")["results"]) == 2
    with pytest.raises(ValueError):
        search(root, "hello", agent_id="../outside")
    with pytest.raises(ValueError):
        search(root, "hello", session_id="../outside/private")
    (root / "conversations").rename(root / "real_archive")
    (root / "conversations").symlink_to(outside.parent)
    assert search(root, "hello")["results"] == []
    assert open_session(root, "private")["error"] == "session_not_found"


def test_large_sessions_are_reported_not_silently_omitted(tmp_path):
    root = tmp_path / "workspace"
    folder = root / "conversations"
    folder.mkdir(parents=True)
    large = folder / "huge.json"
    with large.open("wb") as handle:
        handle.truncate(_MAX_SESSION_BYTES + 1)
    assert search(root, "needle")["skipped_large"] == 1
    result = open_session(root, "huge")
    assert result["error"] == "session_too_large"
    assert result["max_bytes"] == _MAX_SESSION_BYTES


def test_replaced_session_file_cannot_redirect_read(tmp_path, monkeypatch):
    root = tmp_path / "workspace"
    candidate = _session(root, "old", "inside")
    outside = _session(tmp_path / "outside", "old", "outside secret")
    real_open = os.open
    replaced = False

    def replace_before_open(path, flags, *args, **kwargs):
        nonlocal replaced
        if path == "old.json" and not replaced:
            replaced = True
            candidate.unlink()
            candidate.symlink_to(outside)
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(conversation_archive.os, "open", replace_before_open)
    assert search(root, "outside secret")["results"] == []
    assert replaced
    assert open_session(root, "old")["error"] == "session_not_found"


def test_replaced_agent_directory_cannot_redirect_read(tmp_path, monkeypatch):
    root = tmp_path / "workspace"
    candidate = _session(root, "old", "inside", agent="researcher")
    outside = _session(tmp_path / "outside", "old", "outside secret")
    real_open = os.open
    replaced = False

    def replace_before_open(path, flags, *args, **kwargs):
        nonlocal replaced
        if path == "researcher" and not replaced:
            replaced = True
            candidate.unlink()
            candidate.parent.rmdir()
            candidate.parent.symlink_to(outside.parent)
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(conversation_archive.os, "open", replace_before_open)
    assert search(root, "outside secret")["results"] == []
    assert replaced


def test_replaced_workspace_directory_cannot_redirect_read(tmp_path, monkeypatch):
    root = tmp_path / "workspace"
    _session(root, "old", "inside")
    outside = _session(tmp_path / "outside", "old", "outside secret")
    real_open = os.open
    replaced = False

    def replace_before_open(path, flags, *args, **kwargs):
        nonlocal replaced
        if path == "workspace" and not replaced:
            replaced = True
            root.rename(tmp_path / "moved")
            root.symlink_to(outside.parent.parent)
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(conversation_archive.os, "open", replace_before_open)
    assert search(root, "outside secret")["results"] == []
    assert replaced


def test_archive_read_fails_closed_without_nofollow(tmp_path, monkeypatch):
    root = tmp_path / "workspace"
    _session(root, "old", "inside")
    monkeypatch.delattr(conversation_archive.os, "O_NOFOLLOW", raising=False)
    assert search(root, "inside")["results"] == []
    assert open_session(root, "old")["error"] == "unreadable_session"


def test_tool_dispatch_and_permission_metadata(tmp_path, caplog):
    root = tmp_path / "workspace"
    _session(root, "historic", "remember this")
    manager = ToolManager({}, lambda *_args: None, fast_startup=True)
    manager.workspace_root = str(root)
    names = {tool["name"] for tool in manager.get_responses_tools(include_web_search=False)}
    assert {"conversation_search", "conversation_open"} <= names
    for name in ("conversation_search", "conversation_open"):
        assert manager.get_tool_runtime_metadata(name)["mutates_state"] is False
        assert get_tool_operations(name) == [Operation.FILESYSTEM_READ]
        ctx, params = manager._archive_permission_input(
            {"workspace_root": str(tmp_path / "unrelated")},
            {"query": "remember", "_archive_root": str(tmp_path / "unrelated")},
        )
        assert ctx["workspace_root"] == str(root)
        assert extract_resources_from_input(name, params, ctx) == [str(root / "conversations")]
        assert manager.check_tool_permission(name, params, ctx)[0] == PermissionResult.ALLOW
    with caplog.at_level(logging.INFO):
        found = manager.execute_tool("conversation_search", {"query": "remember this"})
        opened = manager.execute_tool("conversation_open", {"session_id": "historic", "limit": 2})
    assert found["results"][0]["session_id"] == "historic"
    assert opened["total_messages"] == 3
    assert "remember this" not in caplog.text
    assert "remember this" not in str(manager.grep_search.messages)
    assert manager._redact_tool_input_for_diagnostics(
        "conversation_search", {"query": "remember this"}
    ) == {"archive": "<private>"}


def test_archive_respects_request_read_policy(tmp_path):
    root = tmp_path / "workspace"
    _session(root, "historic", "private conversation")
    manager = ToolManager({}, lambda *_args: None, fast_startup=True)
    manager.workspace_root = str(root)
    class DenyArchiveReads(PolicyEngine):
        name = "deny_archive_reads"
        priority = 300

        def check_operation(self, operation, resource, context=None):
            if operation == Operation.FILESYSTEM_READ:
                return PermissionResult.DENY, "Archive reads disabled"
            return PermissionResult.ALLOW, "Other operations allowed"

    manager.permission_enforcer.add_policy(DenyArchiveReads())
    for name, args in (
        ("conversation_search", {"query": "private"}),
        ("conversation_open", {"session_id": "historic"}),
    ):
        result = manager.execute_tool(name, args)
        assert "private conversation" not in str(result)
        assert "permission" in str(result).lower() or "denied" in str(result).lower()
