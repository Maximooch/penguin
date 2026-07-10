from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from penguin.tools.runtime import (
    ToolCall,
    ToolExecutionPolicy,
    ToolResult,
    _preview_text,
    execute_tool_calls_serially,
    hash_tool_output,
    legacy_action_result_from_tool_result,
    prepare_model_visible_tool_output,
    tool_result_from_action_result,
    tool_result_with_model_output_policy,
)


def test_preview_text_treats_negative_limit_as_empty() -> None:
    assert _preview_text("secret", max_chars=-1) == ""


def test_model_visible_tool_output_truncates_and_writes_full_artifact(
    tmp_path: Path,
) -> None:
    full_output = "\n".join(f"line-{idx:03d}" for idx in range(100))

    view = prepare_model_visible_tool_output(
        full_output,
        max_chars=180,
        artifact_dir=tmp_path,
        artifact_id="call_read",
        truncation_direction="tail",
    )

    assert view.truncated is True
    assert len(view.model_output) <= 180
    assert "Tool output truncated" in view.model_output
    assert view.byte_count == len(full_output.encode("utf-8"))
    assert view.line_count == 100
    assert view.output_hash == hash_tool_output(full_output)
    assert view.artifact_path is not None
    assert Path(view.artifact_path).read_text(encoding="utf-8") == full_output


def test_model_visible_tool_output_keeps_small_output_inline(tmp_path: Path) -> None:
    view = prepare_model_visible_tool_output(
        "short output",
        max_chars=100,
        artifact_dir=tmp_path,
    )

    assert view.model_output == "short output"
    assert view.full_output == "short output"
    assert view.truncated is False
    assert view.artifact_path is None
    assert list(tmp_path.iterdir()) == []


def test_model_visible_tool_output_handles_tiny_budget(tmp_path: Path) -> None:
    view = prepare_model_visible_tool_output(
        "x" * 100,
        max_chars=12,
        artifact_dir=tmp_path,
        artifact_id="../../unsafe",
    )

    assert view.truncated is True
    assert len(view.model_output) == 12
    assert view.artifact_path is not None
    assert Path(view.artifact_path).name.startswith("tool-output-")
    assert Path(view.artifact_path).read_text(encoding="utf-8") == "x" * 100


def test_model_visible_tool_output_skips_artifact_when_quota_is_exhausted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PENGUIN_TOOL_ARTIFACT_MAX_FILES", "0")

    view = prepare_model_visible_tool_output(
        "x" * 500,
        max_chars=180,
        artifact_dir=tmp_path,
        artifact_id="quota",
    )

    assert view.truncated is True
    assert view.artifact_path is None
    assert "artifact=not_saved" in view.model_output
    assert "artifact_quota_exceeded" in view.model_output
    assert list(tmp_path.iterdir()) == []


def test_tool_result_records_output_metadata() -> None:
    result = ToolResult(
        call_id="call_1",
        name="execute_command",
        status="completed",
        output="a\nb",
        truncated=True,
        truncation_direction="tail",
        artifact_path="/tmp/tool-output-call_1.txt",
    )

    assert result.byte_count == 3
    assert result.line_count == 2
    assert result.output_hash == hash_tool_output("a\nb")
    assert legacy_action_result_from_tool_result(result) == {
        "action": "execute_command",
        "result": "a\nb",
        "status": "completed",
    }


def test_tool_result_policy_omits_full_structured_output_payload(
    tmp_path: Path,
) -> None:
    result = ToolResult(
        call_id="call_1",
        name="read_file",
        status="completed",
        output="line\n" * 100,
        structured_output={
            "path": "large.txt",
            "result": "line\n" * 100,
            "output": "line\n" * 100,
        },
    )

    bounded = tool_result_with_model_output_policy(
        result,
        max_chars=80,
        artifact_dir=tmp_path,
    )

    assert bounded.truncated is True
    assert bounded.structured_output is not None
    assert bounded.structured_output["path"] == "large.txt"
    assert "result" not in bounded.structured_output
    assert "output" not in bounded.structured_output


def test_action_result_to_tool_result_preserves_output_metadata() -> None:
    result = tool_result_from_action_result(
        {
            "action": "execute_command",
            "result": "tail",
            "status": "completed",
            "metadata": {
                "byte_count": 5000,
                "line_count": 250,
                "truncated": True,
                "truncation_direction": "tail",
                "artifact_path": "/tmp/full.txt",
            },
        },
        call_id="call_1",
    )

    assert result.byte_count == 5000
    assert result.line_count == 250
    assert result.truncated is True
    assert result.truncation_direction == "tail"
    assert result.artifact_path == "/tmp/full.txt"


@pytest.mark.asyncio
async def test_serial_scheduler_applies_model_output_policy(tmp_path: Path) -> None:
    [result] = await execute_tool_calls_serially(
        [
            ToolCall(
                id="call_long",
                name="execute_command",
                arguments="printf long",
                source="responses",
            )
        ],
        lambda _tool_call: "line\n" * 100,
        policy=ToolExecutionPolicy(
            max_output_chars=160,
            artifact_dir=tmp_path,
            truncation_direction="tail",
        ),
    )

    assert result.truncated is True
    assert len(result.output) <= 160
    assert "Tool output truncated" in result.output
    assert result.artifact_path is not None
    artifact_text = await asyncio.to_thread(
        Path(result.artifact_path).read_text,
        encoding="utf-8",
    )
    assert artifact_text == "line\n" * 100


@pytest.mark.asyncio
async def test_serial_scheduler_omits_full_output_from_structured_output(
    tmp_path: Path,
) -> None:
    full_output = "line\n" * 100

    [result] = await execute_tool_calls_serially(
        [
            ToolCall(
                id="call_dict_output",
                name="read_file",
                arguments='{"path": "large.txt"}',
                source="responses",
            )
        ],
        lambda _tool_call: {
            "action": "read_file",
            "path": "large.txt",
            "result": full_output,
            "status": "completed",
        },
        policy=ToolExecutionPolicy(
            max_output_chars=160,
            artifact_dir=tmp_path,
            truncation_direction="tail",
        ),
    )

    assert result.truncated is True
    assert result.structured_output is not None
    assert "result" not in result.structured_output
    assert result.structured_output["path"] == "large.txt"
    assert result.artifact_path is not None
