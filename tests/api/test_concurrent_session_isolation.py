"""Concurrent session isolation tests for request-scoped tool execution."""

from __future__ import annotations

import asyncio
import base64
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from penguin.system.execution_context import ExecutionContext, execution_context_scope
from penguin.system.execution_context import get_current_execution_context
from penguin.tools.tool_manager import ToolManager
from penguin.web.routes import MessageRequest, handle_chat_message


def _dummy_log_error(exc: Exception, context: str = "") -> None:
    del exc, context


async def _run_session_flow(
    manager: ToolManager,
    *,
    session_id: str,
    repo_root: Path,
    marker_file: str,
) -> tuple[str, str]:
    marker = f"marker-{session_id}"
    with execution_context_scope(
        ExecutionContext(
            session_id=session_id,
            conversation_id=session_id,
            directory=str(repo_root),
            project_root=str(repo_root),
            workspace_root=str(repo_root),
        )
    ):
        pwd_output = await asyncio.to_thread(
            manager.execute_tool,
            "execute_command",
            {"command": "pwd"},
        )
        await asyncio.to_thread(
            manager.execute_tool,
            "write_to_file",
            {"path": marker_file, "content": marker},
        )
        file_output = await asyncio.to_thread(
            manager.execute_tool,
            "read_file",
            {"path": marker_file},
        )
    return str(pwd_output), str(file_output)


@pytest.mark.asyncio
async def test_parallel_sessions_keep_tool_roots_isolated(tmp_path: Path) -> None:
    repo_a = tmp_path / "repo_a"
    repo_b = tmp_path / "repo_b"
    repo_a.mkdir()
    repo_b.mkdir()

    manager = ToolManager(config={}, log_error_func=_dummy_log_error, fast_startup=True)
    manager._permission_enabled = False

    result_a, result_b = await asyncio.gather(
        _run_session_flow(
            manager,
            session_id="session_a",
            repo_root=repo_a,
            marker_file="marker.txt",
        ),
        _run_session_flow(
            manager,
            session_id="session_b",
            repo_root=repo_b,
            marker_file="marker.txt",
        ),
    )

    pwd_a, file_a = result_a
    pwd_b, file_b = result_b

    assert str(repo_a.resolve()) in pwd_a
    assert str(repo_b.resolve()) in pwd_b
    assert str(repo_b.resolve()) not in pwd_a
    assert str(repo_a.resolve()) not in pwd_b

    assert "marker-session_a" in file_a
    assert "marker-session_b" in file_b
    assert "marker-session_b" not in file_a
    assert "marker-session_a" not in file_b

    assert (repo_a / "marker.txt").read_text(encoding="utf-8") == "marker-session_a"
    assert (repo_b / "marker.txt").read_text(encoding="utf-8") == "marker-session_b"


@pytest.mark.asyncio
async def test_parallel_chat_requests_keep_execution_context_isolated(
    tmp_path: Path,
) -> None:
    repo_a = tmp_path / "chat_repo_a"
    repo_b = tmp_path / "chat_repo_b"
    repo_a.mkdir()
    repo_b.mkdir()

    captured_contexts: list[tuple[str | None, str | None]] = []

    class _Core:
        def __init__(self) -> None:
            self.runtime_config = SimpleNamespace(
                workspace_root=str(tmp_path),
                project_root=str(tmp_path),
                active_root=str(tmp_path),
            )
            self._opencode_session_directories: dict[str, str] = {}

        async def process(self, **kwargs):  # type: ignore[no-untyped-def]
            del kwargs
            current = get_current_execution_context()
            session_id = current.session_id if current else None
            directory = current.directory if current else None
            captured_contexts.append((session_id, directory))
            await asyncio.sleep(0.02)
            return {
                "assistant_response": f"session={session_id}|dir={directory}",
                "action_results": [],
            }

    core = _Core()

    async def _send(session_id: str, directory: Path):
        request = MessageRequest(
            text=f"hello from {session_id}",
            session_id=session_id,
            conversation_id=session_id,
            directory=str(directory),
            streaming=False,
        )
        return await handle_chat_message(request, core=cast(Any, core))

    response_a, response_b = await asyncio.gather(
        _send("chat_session_a", repo_a),
        _send("chat_session_b", repo_b),
    )

    assert str(repo_a.resolve()) in response_a["response"]
    assert str(repo_b.resolve()) in response_b["response"]
    assert "chat_session_a" in response_a["response"]
    assert "chat_session_b" in response_b["response"]

    assert ("chat_session_a", str(repo_a.resolve())) in captured_contexts
    assert ("chat_session_b", str(repo_b.resolve())) in captured_contexts
    assert core._opencode_session_directories["chat_session_a"] == str(repo_a.resolve())
    assert core._opencode_session_directories["chat_session_b"] == str(repo_b.resolve())


@pytest.mark.asyncio
async def test_chat_binding_prefers_session_id_over_conversation_id(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "chat_repo"
    repo.mkdir()

    class _Core:
        def __init__(self) -> None:
            self.runtime_config = SimpleNamespace(
                workspace_root=str(tmp_path),
                project_root=str(tmp_path),
                active_root=str(tmp_path),
            )
            self._opencode_session_directories = {
                "session_primary": str(repo.resolve())
            }

        async def process(self, **kwargs):  # type: ignore[no-untyped-def]
            del kwargs
            return {"assistant_response": "ok", "action_results": []}

    core = _Core()
    request = MessageRequest(
        text="ping",
        session_id="session_primary",
        conversation_id="stale_conversation_id",
        directory=str(repo),
        streaming=False,
    )

    response = await handle_chat_message(request, core=cast(Any, core))

    assert response["response"] == "ok"
    assert core._opencode_session_directories["session_primary"] == str(repo.resolve())
    assert "stale_conversation_id" not in core._opencode_session_directories


@pytest.mark.asyncio
async def test_rest_chat_respects_streaming_flag(tmp_path: Path) -> None:
    repo = tmp_path / "chat_repo_non_streaming"
    repo.mkdir()
    seen_kwargs: dict[str, Any] = {}

    class _Core:
        def __init__(self) -> None:
            self.runtime_config = SimpleNamespace(
                workspace_root=str(tmp_path),
                project_root=str(tmp_path),
                active_root=str(tmp_path),
            )
            self._opencode_session_directories: dict[str, str] = {}

        async def process(self, **kwargs):  # type: ignore[no-untyped-def]
            seen_kwargs.update(kwargs)
            return {"assistant_response": "ok", "action_results": []}

    core = _Core()
    request = MessageRequest(
        text="ping",
        session_id="session_non_streaming",
        directory=str(repo),
        streaming=True,
        include_reasoning=False,
    )

    response = await handle_chat_message(request, core=cast(Any, core))

    assert response["response"] == "ok"
    assert seen_kwargs["streaming"] is True


@pytest.mark.asyncio
async def test_rest_chat_parts_forward_context_and_materialize_images(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "chat_repo_parts"
    repo.mkdir()
    seen_kwargs: dict[str, Any] = {}

    class _Core:
        def __init__(self) -> None:
            self.runtime_config = SimpleNamespace(
                workspace_root=str(tmp_path),
                project_root=str(tmp_path),
                active_root=str(tmp_path),
            )
            self._opencode_session_directories: dict[str, str] = {}

        async def process(self, **kwargs):  # type: ignore[no-untyped-def]
            seen_kwargs.update(kwargs)
            image_paths = kwargs.get("input_data", {}).get("image_paths", [])
            if image_paths:
                seen_kwargs["image_exists_during_process"] = Path(
                    image_paths[0]
                ).exists()
            return {"assistant_response": "ok", "action_results": []}

    core = _Core()
    request = MessageRequest(
        text="describe image",
        session_id="session_parts",
        directory=str(repo),
        streaming=False,
        parts=[
            {
                "type": "file",
                "mime": "image/png",
                "url": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAOQOt9kAAAAASUVORK5CYII=",
                "source": {"type": "file", "path": "image.png"},
            },
            {
                "type": "file",
                "mime": "text/plain",
                "url": "README.md",
                "source": {"type": "file", "path": "README.md"},
            },
        ],
    )

    response = await handle_chat_message(request, core=cast(Any, core))

    assert response["response"] == "ok"
    assert seen_kwargs["context_files"] == ["README.md"]
    image_paths = seen_kwargs["input_data"]["image_paths"]
    assert isinstance(image_paths, list)
    assert image_paths
    image_path = image_paths[0]
    assert isinstance(image_path, str)
    assert not image_path.startswith("data:")
    assert seen_kwargs["image_exists_during_process"] is True
    assert not Path(image_path).exists()


@pytest.mark.asyncio
async def test_rest_chat_accepts_local_image_paths_without_temp_cleanup(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "chat_repo_local_image"
    repo.mkdir()
    image = repo / "drag.png"
    image.write_bytes(
        base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAOQOt9kAAAAASUVORK5CYII="
        )
    )

    seen_kwargs: dict[str, Any] = {}

    class _Core:
        def __init__(self) -> None:
            self.runtime_config = SimpleNamespace(
                workspace_root=str(tmp_path),
                project_root=str(tmp_path),
                active_root=str(tmp_path),
            )
            self._opencode_session_directories: dict[str, str] = {}

        async def process(self, **kwargs):  # type: ignore[no-untyped-def]
            seen_kwargs.update(kwargs)
            image_paths = kwargs.get("input_data", {}).get("image_paths", [])
            if image_paths:
                seen_kwargs["image_exists_during_process"] = Path(
                    image_paths[0]
                ).exists()
            return {"assistant_response": "ok", "action_results": []}

    core = _Core()
    request = MessageRequest(
        text="describe image",
        session_id="session_local_image",
        directory=str(repo),
        streaming=False,
        image_paths=[str(image)],
        parts=[
            {
                "type": "file",
                "mime": "image/png",
                "url": str(image),
                "source": {"type": "file", "path": str(image)},
            }
        ],
    )

    response = await handle_chat_message(request, core=cast(Any, core))

    assert response["response"] == "ok"
    image_paths = seen_kwargs["input_data"]["image_paths"]
    assert image_paths == [str(image)]
    assert seen_kwargs["image_exists_during_process"] is True
    assert image.exists()


@pytest.mark.asyncio
async def test_rest_chat_model_selector_loads_requested_model(tmp_path: Path) -> None:
    repo = tmp_path / "chat_repo_model_switch"
    repo.mkdir()

    class _Core:
        def __init__(self) -> None:
            self.runtime_config = SimpleNamespace(
                workspace_root=str(tmp_path),
                project_root=str(tmp_path),
                active_root=str(tmp_path),
            )
            self.config = SimpleNamespace(model_configs={})
            self._opencode_session_directories: dict[str, str] = {}
            self._current_model = {
                "provider": "openrouter",
                "model": "openai/gpt-4.1-mini",
            }
            self.load_calls: list[str] = []

        def get_current_model(self) -> dict[str, str]:
            return dict(self._current_model)

        async def load_model(self, model_id: str) -> bool:
            self.load_calls.append(model_id)
            if model_id != "openai/gpt-5-mini":
                return False
            self._current_model = {
                "provider": "openrouter",
                "model": "openai/gpt-5-mini",
            }
            return True

        async def process(self, **kwargs):  # type: ignore[no-untyped-def]
            del kwargs
            return {"assistant_response": "ok", "action_results": []}

    core = _Core()
    request = MessageRequest(
        text="ping",
        model="openrouter/openai/gpt-5-mini",
        session_id="session_model_switch",
        directory=str(repo),
        streaming=False,
    )

    response = await handle_chat_message(request, core=cast(Any, core))

    assert response["response"] == "ok"
    assert core.load_calls == ["openrouter/openai/gpt-5-mini", "openai/gpt-5-mini"]


@pytest.mark.asyncio
async def test_rest_chat_model_selector_skips_reloading_current_model(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "chat_repo_model_same"
    repo.mkdir()

    class _Core:
        def __init__(self) -> None:
            self.runtime_config = SimpleNamespace(
                workspace_root=str(tmp_path),
                project_root=str(tmp_path),
                active_root=str(tmp_path),
            )
            self._opencode_session_directories: dict[str, str] = {}
            self.load_calls: list[str] = []

        def get_current_model(self) -> dict[str, str]:
            return {
                "provider": "openrouter",
                "model": "openai/gpt-5-mini",
            }

        async def load_model(self, model_id: str) -> bool:
            self.load_calls.append(model_id)
            return True

        async def process(self, **kwargs):  # type: ignore[no-untyped-def]
            del kwargs
            return {"assistant_response": "ok", "action_results": []}

    core = _Core()
    request = MessageRequest(
        text="ping",
        model="openrouter/openai/gpt-5-mini",
        session_id="session_model_same",
        directory=str(repo),
        streaming=False,
    )

    response = await handle_chat_message(request, core=cast(Any, core))

    assert response["response"] == "ok"
    assert core.load_calls == []


@pytest.mark.asyncio
async def test_parallel_chat_requests_sustained_isolation(tmp_path: Path) -> None:
    repo_a = tmp_path / "sustained_repo_a"
    repo_b = tmp_path / "sustained_repo_b"
    repo_a.mkdir()
    repo_b.mkdir()

    captured_contexts: list[tuple[str | None, str | None]] = []

    class _Core:
        def __init__(self) -> None:
            self.runtime_config = SimpleNamespace(
                workspace_root=str(tmp_path),
                project_root=str(tmp_path),
                active_root=str(tmp_path),
            )
            self._opencode_session_directories: dict[str, str] = {}

        async def process(self, **kwargs):  # type: ignore[no-untyped-def]
            del kwargs
            current = get_current_execution_context()
            session_id = current.session_id if current else None
            directory = current.directory if current else None
            captured_contexts.append((session_id, directory))
            await asyncio.sleep(0.005)
            return {
                "assistant_response": f"session={session_id}|dir={directory}",
                "action_results": [],
            }

    core = _Core()

    async def _send(session_id: str, directory: Path, turn: int) -> dict[str, Any]:
        request = MessageRequest(
            text=f"turn {turn} from {session_id}",
            session_id=session_id,
            conversation_id=session_id,
            directory=str(directory),
            streaming=False,
        )
        return await handle_chat_message(request, core=cast(Any, core))

    for turn in range(1, 11):
        response_a, response_b = await asyncio.gather(
            _send("sustained_a", repo_a, turn),
            _send("sustained_b", repo_b, turn),
        )
        assert str(repo_a.resolve()) in response_a["response"]
        assert str(repo_b.resolve()) in response_b["response"]
        assert "sustained_a" in response_a["response"]
        assert "sustained_b" in response_b["response"]

    assert len(captured_contexts) == 20
    assert all(
        not (session_id == "sustained_a" and directory == str(repo_b.resolve()))
        for session_id, directory in captured_contexts
    )
    assert all(
        not (session_id == "sustained_b" and directory == str(repo_a.resolve()))
        for session_id, directory in captured_contexts
    )
    assert core._opencode_session_directories["sustained_a"] == str(repo_a.resolve())
    assert core._opencode_session_directories["sustained_b"] == str(repo_b.resolve())
