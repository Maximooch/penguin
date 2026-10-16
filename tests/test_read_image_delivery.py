"""Image delivery contracts through native calls and ordered batches (issue #113)."""

import base64
import io
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from PIL import Image

from penguin.engine import Engine
from penguin.llm.adapters.openai import OpenAIAdapter
from penguin.llm.model_config import ModelConfig
from penguin.llm.runtime import execute_pending_tool_calls
from penguin.system.conversation import ConversationSystem
from penguin.tools.image_tools import ReadImageTool
from penguin.tools.runtime import ToolExecutionPolicy


@pytest.mark.asyncio
@pytest.mark.parametrize("output_limit", [80, 2000])
@pytest.mark.parametrize("route", ["native", "codex_oauth"])
@pytest.mark.parametrize("batched", [False, True])
@pytest.mark.parametrize("failure", [None, "missing", "corrupt", "denied"])
async def test_image_pixels_reach_provider_after_all_tool_replies(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    batched: bool,
    failure: str | None,
    route: str,
    output_limit: int,
) -> None:
    """Exercise real ingest, normalization, storage, formatting and wire encoding."""
    path = tmp_path / "recognizable.png"
    if failure == "corrupt":
        path.write_bytes(b"not an image")
    elif failure != "missing":
        Image.new("RGB", (16, 12), (240, 20, 10)).save(path)

    def enforce_path(candidate: Path, **kwargs: Any) -> Path:
        if failure == "denied":
            raise PermissionError("outside workspace")
        return candidate

    monkeypatch.setattr("penguin.tools.image_tools.enforce_allowed_path", enforce_path)
    calls = [
        {
            "id": "image",
            "name": "read_image",
            "arguments": json.dumps({"path": str(path)}),
        }
    ]
    if batched:
        calls = [
            {
                "id": "batch",
                "name": "ordered_tool_batch",
                "arguments": json.dumps(
                    {
                        "tool_uses": [
                            {"tool": "read_image", "arguments": {"path": str(path)}}
                        ]
                    }
                ),
            }
        ]
    calls.append({"id": "other", "name": "other_tool", "arguments": "{}"})

    class Manager:
        def execute_tool(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
            if name == "read_image":
                return ReadImageTool().execute(**args)
            return {"result": "other tool completed"}

    conversation = ConversationSystem(None, None)
    conversation.add_message("assistant", "")
    engine = object.__new__(Engine)
    manager = SimpleNamespace(conversation=conversation)
    await execute_pending_tool_calls(
        api_client=SimpleNamespace(
            client_handler=SimpleNamespace(
                get_and_clear_pending_tool_calls=lambda: calls
            ),
            model_config=None,
        ),
        tool_manager=Manager(),
        execution_policy=ToolExecutionPolicy(
            max_output_chars=output_limit, artifact_dir=tmp_path
        ),
        persist_action_result=lambda action, context: conversation.add_action_result(
            action_type=action["action"],
            result=action["result"],
            status=action["status"],
            **context,
        ),
        persist_image_artifacts=lambda action: engine._persist_tool_image_artifacts(
            manager, action
        ),
    )
    messages = conversation._format_session_messages(conversation.session)
    assert [m["role"] for m in messages] == (
        ["assistant", "tool", "tool", "user"]
        if failure is None
        else ["assistant", "tool", "tool"]
    )
    assert conversation.session.messages[1].metadata["status"] == (
        "error" if failure else "completed"
    )
    adapter = OpenAIAdapter(
        ModelConfig(
            model="gpt-5",
            provider="openai",
            client_preference="native",
            api_key="sk-test",
        )
    )
    monkeypatch.setattr(
        adapter,
        "_peek_oauth_record_for_prepare",
        lambda: {"type": "oauth", "access": "test-access"}
        if route == "codex_oauth"
        else None,
    )
    prepared = await adapter.prepare_request(messages)
    items = prepared.body["input"]
    if route == "codex_oauth":
        assert [item["type"] for item in items].count("function_call_output") == 2
    if isinstance(items, str):
        assert failure is not None
        assert "error" in items.lower() or "tool output truncated" in items.lower()
        return
    images = [
        part
        for item in items
        for part in item.get("content", [])
        if part.get("type") == "input_image"
    ]
    assert len(images) == (0 if failure else 1)
    if images:
        pixels = base64.b64decode(images[0]["image_url"].split(",", 1)[1])
        with Image.open(io.BytesIO(pixels)) as image:
            assert image.size == (16, 12)
            red, green, blue = image.getpixel((8, 6))
            assert red > 220 and green < 40 and blue < 30
    else:
        assert (
            "error" in messages[1]["content"].lower()
            or "failed" in messages[1]["content"].lower()
            or "tool output truncated" in messages[1]["content"].lower()
        )
