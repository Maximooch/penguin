"""Tests for OpenCode action mapping runtime helpers."""

from __future__ import annotations

from typing import Any

from hypothesis import given, settings, strategies as st

from penguin.core_runtime import action_mapping


def test_map_action_to_tool_maps_apply_diff_to_unified_edit_metadata() -> None:
    mapped_tool, tool_input, metadata = action_mapping.map_action_to_tool(
        "apply_diff",
        {"path": "src/app.py", "diff": "@@\n-old\n+new\n"},
    )

    assert mapped_tool == "edit"
    assert tool_input == {"filePath": "src/app.py"}
    assert metadata["diff"].startswith("--- a/src/app.py\n+++ b/src/app.py\n")
    assert "+new" in metadata["diff"]


def test_map_action_result_metadata_keeps_error_diff_as_attempted_diff() -> None:
    metadata = action_mapping.map_action_result_metadata(
        "patch_file",
        "Error applying patch",
        existing={"diff": "--- a/file.py\n+++ b/file.py\n@@\n-old\n+new\n"},
        tool_input={"filePath": "file.py"},
        status="error",
    )

    assert "diff" not in metadata
    assert metadata["attemptedDiff"].startswith("--- a/file.py")


def test_map_action_result_metadata_builds_subagent_completion_card() -> None:
    metadata = action_mapping.map_action_result_metadata(
        "spawn_sub_agent",
        '{"session_id": "session_child", "session_title": "Child Build"}',
        existing={"summary": [{"state": {"status": "running"}}]},
        status="completed",
    )

    assert metadata["sessionId"] == "session_child"
    assert metadata["title"] == "Child Build"
    assert metadata["summary"] == [
        {
            "id": "session_child",
            "tool": "subagent",
            "state": {"status": "completed", "title": "Child Build"},
        }
    ]


def test_map_action_to_tool_accepts_parser_injection_for_apply_patch_errors() -> None:
    def parse_apply_patch(_params: Any) -> dict[str, Any]:
        return {
            "patch": "*** Begin Patch\n*** Update File: src/app.py\n@@\n",
            "error": "malformed patch",
        }

    mapped_tool, tool_input, metadata = action_mapping.map_action_to_tool(
        "apply_patch",
        {"patch": "ignored"},
        parse_apply_patch=parse_apply_patch,
    )

    assert mapped_tool == "edit"
    assert tool_input == {"filePath": "(patch)"}
    assert metadata["files"] == ["src/app.py"]
    assert metadata["diff"].startswith("*** Begin Patch")


def test_parse_action_payload_ignores_non_object_json() -> None:
    assert action_mapping.parse_action_payload("[1, 2, 3]") == {}
    assert action_mapping.parse_action_payload("not-json") == {}
    assert action_mapping.parse_action_payload({"path": "README.md"}) == {
        "path": "README.md"
    }


@settings(max_examples=50)
@given(
    items=st.lists(
        st.fixed_dictionaries(
            {
                "id": st.one_of(st.none(), st.text(max_size=8)),
                "content": st.one_of(st.none(), st.text(max_size=30)),
                "status": st.one_of(st.none(), st.text(max_size=12)),
                "priority": st.one_of(st.none(), st.text(max_size=12)),
            }
        ),
        max_size=30,
    )
)
def test_normalize_todo_items_produces_unique_valid_records(
    items: list[dict[str, Any]],
) -> None:
    todos = action_mapping.normalize_todo_items(items)

    ids = [todo["id"] for todo in todos]
    assert len(ids) == len(set(ids))
    for todo in todos:
        assert todo["content"]
        assert todo["status"] in {"pending", "in_progress", "completed", "cancelled"}
        assert todo["priority"] in {"high", "medium", "low"}
