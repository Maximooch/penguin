"""Tests for OpenCode action mapping runtime helpers."""

from __future__ import annotations

import string
from typing import Any

import pytest
from hypothesis import given, settings, strategies as st

from penguin.core_runtime import action_mapping


@pytest.mark.parametrize(
    ("action", "params", "expected_tool", "expected_values"),
    [
        (
            "code_execution",
            {"code": "print(13)"},
            "bash",
            {"command": "print(13)", "description": "IPython"},
        ),
        (
            "execute_command",
            {"command": "pytest tests -q"},
            "bash",
            {"command": "pytest tests -q", "description": "Shell"},
        ),
        (
            "insert_lines",
            {"path": "src/main.py", "after_line": 4, "new_content": "print('x')"},
            "edit",
            {"filePath": "src/main.py", "afterLine": 4},
        ),
        (
            "delete_lines",
            {"path": "src/main.py", "start_line": 5, "end_line": 7},
            "edit",
            {"filePath": "src/main.py", "startLine": 5, "endLine": 7},
        ),
        (
            "enhanced_write",
            {"path": "README.md", "content": "hello", "backup": True},
            "write",
            {"filePath": "README.md", "content": "hello", "backup": True},
        ),
        (
            "workspace_search",
            {"query": "TODO"},
            "grep",
            {"pattern": "TODO", "path": "."},
        ),
        (
            "enhanced_diff",
            {"file1": "src/a.py", "file2": "src/b.py", "semantic": True},
            "read",
            {
                "filePath": "src/a.py",
                "comparePath": "src/b.py",
                "semantic": True,
            },
        ),
        (
            "todowrite",
            {
                "todos": [
                    {
                        "id": "todo_1",
                        "content": "Track todo progress",
                        "status": "pending",
                        "priority": "medium",
                    }
                ]
            },
            "todowrite",
            {
                "todos": [
                    {
                        "id": "todo_1",
                        "content": "Track todo progress",
                        "status": "pending",
                        "priority": "medium",
                    }
                ]
            },
        ),
    ],
)
def test_map_action_to_tool_covers_common_runtime_workflows(
    action: str,
    params: Any,
    expected_tool: str,
    expected_values: dict[str, Any],
) -> None:
    mapped_tool, tool_input, metadata = action_mapping.map_action_to_tool(
        action,
        params,
    )

    assert mapped_tool == expected_tool
    for key, value in expected_values.items():
        assert tool_input.get(key) == value
    assert isinstance(metadata, dict)


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


def test_map_action_result_metadata_extracts_diff_and_file_path() -> None:
    metadata = action_mapping.map_action_result_metadata(
        "replace_lines",
        (
            "Replaced lines 2-2 in src/main.py\n"
            "--- a/src/main.py\n"
            "+++ b/src/main.py\n"
            "@@ -1,3 +1,3 @@\n"
            " line1\n"
            "-line2\n"
            "+line2_updated\n"
            " line3\n"
        ),
        existing={"source": "runtime-test"},
        tool_input={"filePath": "src/main.py"},
    )

    assert metadata["source"] == "runtime-test"
    assert metadata["filePath"] == "src/main.py"
    assert metadata["diff"].startswith("--- a/src/main.py")
    assert "+line2_updated" in metadata["diff"]


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


def test_apply_diff_string_payload_strips_apply_flag_after_body_colons() -> None:
    mapped_tool, tool_input, metadata = action_mapping.map_action_to_tool(
        "apply_diff",
        "src/app.py:@@\n-old: value\n+new: value\n:false",
    )

    assert mapped_tool == "edit"
    assert tool_input == {"filePath": "src/app.py"}
    assert "-old: value" in metadata["diff"]
    assert "+new: value" in metadata["diff"]
    assert not metadata["diff"].endswith(":false")


def test_question_action_parses_json_list_string_and_filters_corrupt_items() -> None:
    mapped_tool, tool_input, metadata = action_mapping.map_action_to_tool(
        "question",
        '[{"question": "Proceed?", "header": "Next"}, "bad", 3]',
    )

    assert mapped_tool == "question"
    assert tool_input == {"questions": [{"question": "Proceed?", "header": "Next"}]}
    assert metadata == {}


def test_summary_status_ignores_corrupt_task_card_metadata() -> None:
    assert action_mapping.summary_status({"summary": "bad"}, "fallback") == "fallback"
    assert action_mapping.summary_status({"summary": [{}]}, "fallback") == "fallback"
    assert (
        action_mapping.summary_status({"summary": [{"state": {"status": ""}}]}, "x")
        == "x"
    )


def test_spawn_subagent_task_card_uses_fallbacks_for_corrupt_payload() -> None:
    tool_input, metadata = action_mapping.build_spawn_subagent_task_card("not-json")

    assert tool_input == {
        "description": "Subagent session for subagent",
        "prompt": "",
        "subagent_type": "subagent",
    }
    assert metadata["summary"] == [
        {
            "id": "subagent",
            "tool": "subagent",
            "state": {"status": "running"},
        }
    ]


def test_result_metadata_merges_event_metadata_before_error_diff_rewrite() -> None:
    metadata = action_mapping.map_action_result_metadata(
        "apply_diff",
        "failed",
        existing={"diff": "--- a/a.py\n+++ b/a.py\n@@\n-old\n+new\n"},
        status="error",
        event_metadata={"sessionId": "session_child", "diff": "attempted"},
    )

    assert metadata["sessionId"] == "session_child"
    assert metadata["attemptedDiff"] == "attempted"
    assert "diff" not in metadata


def test_extract_result_file_paths_ignores_corrupt_payloads() -> None:
    assert action_mapping.extract_result_file_paths("not-json") == []
    assert action_mapping.extract_result_file_paths({"files": [1, None, ""]}) == []


@settings(max_examples=80, deadline=None)
@given(
    action=st.text(max_size=24),
    params=st.one_of(
        st.none(),
        st.integers(min_value=-100, max_value=100),
        st.text(max_size=80),
        st.dictionaries(
            keys=st.text(min_size=0, max_size=16),
            values=st.one_of(
                st.none(),
                st.booleans(),
                st.integers(min_value=-100, max_value=100),
                st.text(max_size=40),
            ),
            max_size=8,
        ),
    ),
)
def test_map_action_to_tool_preserves_basic_tool_contract(
    action: str,
    params: Any,
) -> None:
    mapped_tool, tool_input, metadata = action_mapping.map_action_to_tool(
        action,
        params,
    )

    assert isinstance(mapped_tool, str)
    assert mapped_tool
    assert isinstance(tool_input, dict)
    assert isinstance(metadata, dict)


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


@settings(max_examples=50)
@given(
    paths=st.lists(
        st.text(
            alphabet=string.ascii_letters + string.digits + "/._-",
            min_size=1,
            max_size=16,
        ).filter(lambda value: value.strip() not in {"", ".", ".."}),
        min_size=1,
        max_size=20,
    )
)
def test_extract_result_file_paths_dedupes_in_first_seen_order(
    paths: list[str],
) -> None:
    payload = {
        "file": paths[0],
        "files": paths,
        "created": list(reversed(paths)),
        "files_edited": paths[:3],
    }

    result = action_mapping.extract_result_file_paths(payload)

    expected: list[str] = []
    for path in [paths[0], *paths, *reversed(paths), *paths[:3]]:
        if path not in expected:
            expected.append(path)
    assert result == expected
