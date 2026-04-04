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
from penguin.llm.model_config import ModelConfig
from penguin.llm.openrouter_gateway import OpenRouterGateway
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
    entered_sessions: list[str] = []
    both_started = asyncio.Event()
    release_process = asyncio.Event()
    active_calls = 0
    max_active_calls = 0

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
            nonlocal active_calls, max_active_calls
            current = get_current_execution_context()
            session_id = current.session_id if current else None
            directory = current.directory if current else None
            captured_contexts.append((session_id, directory))
            if isinstance(session_id, str):
                entered_sessions.append(session_id)
            active_calls += 1
            max_active_calls = max(max_active_calls, active_calls)
            if len(entered_sessions) >= 2:
                both_started.set()
            try:
                await release_process.wait()
            finally:
                active_calls -= 1
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

    task_a = asyncio.create_task(_send("chat_session_a", repo_a))
    task_b = asyncio.create_task(_send("chat_session_b", repo_b))
    try:
        await asyncio.wait_for(both_started.wait(), timeout=0.2)
        assert max_active_calls == 2
    finally:
        release_process.set()
    response_a, response_b = await asyncio.gather(task_a, task_b)

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
    seen_kwargs: dict[str, Any] = {}

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
            seen_kwargs.update(kwargs)
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
    assert seen_kwargs["conversation_id"] == "session_primary"


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
async def test_rest_chat_applies_reasoning_variant_per_request(tmp_path: Path) -> None:
    repo = tmp_path / "chat_repo_variant"
    repo.mkdir()
    seen: dict[str, Any] = {}

    class _Core:
        def __init__(self) -> None:
            self.runtime_config = SimpleNamespace(
                workspace_root=str(tmp_path),
                project_root=str(tmp_path),
                active_root=str(tmp_path),
            )
            self._opencode_session_directories: dict[str, str] = {}
            self.model_config = SimpleNamespace(
                reasoning_enabled=False,
                reasoning_effort=None,
                reasoning_max_tokens=1234,
                reasoning_exclude=False,
            )

        async def process(self, **kwargs):  # type: ignore[no-untyped-def]
            del kwargs
            seen["enabled"] = self.model_config.reasoning_enabled
            seen["effort"] = self.model_config.reasoning_effort
            seen["max_tokens"] = self.model_config.reasoning_max_tokens
            return {"assistant_response": "ok", "action_results": []}

    core = _Core()
    request = MessageRequest(
        text="ping",
        session_id="session_variant",
        directory=str(repo),
        streaming=False,
    )
    setattr(request, "variant", "high")

    response = await handle_chat_message(request, core=cast(Any, core))

    assert response["response"] == "ok"
    assert seen["enabled"] is True
    assert seen["effort"] == "high"
    assert seen["max_tokens"] is None
    assert core.model_config.reasoning_enabled is False
    assert core.model_config.reasoning_effort is None
    assert core.model_config.reasoning_max_tokens == 1234
    assert not hasattr(core.model_config, "supports_reasoning")


@pytest.mark.asyncio
async def test_rest_chat_variant_emits_outbound_reasoning_payload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repo = tmp_path / "chat_repo_variant_outbound"
    repo.mkdir()
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    captured: dict[str, Any] = {}

    class _Core:
        def __init__(self) -> None:
            self.runtime_config = SimpleNamespace(
                workspace_root=str(tmp_path),
                project_root=str(tmp_path),
                active_root=str(tmp_path),
            )
            self._opencode_session_directories: dict[str, str] = {}
            self.model_config = ModelConfig(
                model="z-ai/glm-5",
                provider="openrouter",
                client_preference="openrouter",
                streaming_enabled=False,
                reasoning_enabled=False,
                reasoning_effort=None,
                reasoning_max_tokens=None,
                reasoning_exclude=False,
                supports_reasoning=False,
            )

        async def process(self, **kwargs):  # type: ignore[no-untyped-def]
            del kwargs
            gateway = OpenRouterGateway(self.model_config)

            async def _fake_direct(
                request_params: dict[str, Any],
                reasoning_config: dict[str, Any],
                use_streaming: bool,
                stream_callback: Any,
            ) -> str:
                del stream_callback
                captured["request_reasoning"] = request_params.get("reasoning")
                captured["reasoning_config"] = dict(reasoning_config)
                captured["use_streaming"] = use_streaming
                return "ok"

            monkeypatch.setattr(
                gateway, "_direct_api_call_with_reasoning", _fake_direct
            )
            response = await gateway.get_response(
                messages=[{"role": "user", "content": "ping"}],
                stream=False,
            )
            return {"assistant_response": response, "action_results": []}

    core = _Core()
    request = MessageRequest(
        text="ping",
        session_id="session_variant_payload",
        directory=str(repo),
        streaming=False,
    )
    setattr(request, "variant", "xhigh")

    response = await handle_chat_message(request, core=cast(Any, core))

    assert response["response"] == "ok"
    assert captured["use_streaming"] is False
    assert captured["reasoning_config"] == {"effort": "xhigh"}
    assert captured["request_reasoning"] == {"effort": "xhigh"}
    assert core.model_config.reasoning_enabled is False
    assert core.model_config.reasoning_effort is None
    assert core.model_config.reasoning_max_tokens is None
    assert core.model_config.supports_reasoning is False


@pytest.mark.asyncio
async def test_rest_chat_auto_refreshes_default_session_title(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "chat_repo_auto_title"
    repo.mkdir()
    summarize_calls: list[str] = []

    class _EventBus:
        def __init__(self) -> None:
            self.events: list[tuple[str, dict[str, Any]]] = []

        async def emit(self, event_type: str, data: dict[str, Any]) -> None:
            self.events.append((event_type, data))

    class _Core:
        def __init__(self) -> None:
            self.runtime_config = SimpleNamespace(
                workspace_root=str(tmp_path),
                project_root=str(tmp_path),
                active_root=str(tmp_path),
            )
            self._opencode_session_directories: dict[str, str] = {}
            self.event_bus = _EventBus()

        async def process(self, **kwargs):  # type: ignore[no-untyped-def]
            del kwargs
            return {"assistant_response": "ok", "action_results": []}

    async def _fake_summarize(
        _core: Any,
        session_id: str,
        *,
        provider_id: str | None = None,
        model_id: str | None = None,
        fallback_text: str | None = None,
    ) -> dict[str, Any]:
        del provider_id, model_id
        assert fallback_text == "ping"
        summarize_calls.append(session_id)
        return {
            "changed": True,
            "title": "Auto title",
            "source": "generated",
            "info": {"id": session_id, "title": "Auto title"},
        }

    def _fake_get_session_info(_core: Any, session_id: str) -> dict[str, Any]:
        return {"id": session_id, "title": f"Session {session_id[-8:]}"}

    def _fake_get_session_metadata_title(_core: Any, _session_id: str) -> str:
        return ""

    monkeypatch.setattr("penguin.web.routes.summarize_session_title", _fake_summarize)
    monkeypatch.setattr("penguin.web.routes.get_session_info", _fake_get_session_info)
    monkeypatch.setattr(
        "penguin.web.routes.get_session_metadata_title",
        _fake_get_session_metadata_title,
    )

    core = _Core()
    request = MessageRequest(
        text="ping",
        session_id="session_auto_title",
        conversation_id="session_auto_title",
        directory=str(repo),
        streaming=False,
    )

    response = await handle_chat_message(request, core=cast(Any, core))
    assert response["response"] == "ok"

    for _ in range(20):
        tasks = getattr(core, "_opencode_title_tasks", {})
        if not tasks:
            break
        await asyncio.sleep(0.01)

    assert summarize_calls == ["session_auto_title"]
    assert core.event_bus.events
    event_type, event_payload = core.event_bus.events[-1]
    assert event_type == "opencode_event"
    assert event_payload["type"] == "session.updated"


@pytest.mark.asyncio
async def test_rest_chat_skips_auto_title_refresh_for_custom_title(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "chat_repo_custom_title"
    repo.mkdir()
    summarize_calls: list[str] = []

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
            return {"assistant_response": "ok", "action_results": []}

    async def _fake_summarize(
        _core: Any,
        session_id: str,
        *,
        provider_id: str | None = None,
        model_id: str | None = None,
        fallback_text: str | None = None,
    ) -> dict[str, Any]:
        del provider_id, model_id, fallback_text
        summarize_calls.append(session_id)
        return {
            "changed": False,
            "title": "Custom title",
            "source": "existing",
            "info": {"id": session_id, "title": "Custom title"},
        }

    def _fake_get_session_info(_core: Any, session_id: str) -> dict[str, Any]:
        return {"id": session_id, "title": "Custom title"}

    def _fake_get_session_metadata_title(_core: Any, _session_id: str) -> str:
        return "Custom title"

    monkeypatch.setattr("penguin.web.routes.summarize_session_title", _fake_summarize)
    monkeypatch.setattr("penguin.web.routes.get_session_info", _fake_get_session_info)
    monkeypatch.setattr(
        "penguin.web.routes.get_session_metadata_title",
        _fake_get_session_metadata_title,
    )

    core = _Core()
    request = MessageRequest(
        text="ping",
        session_id="session_custom_title",
        conversation_id="session_custom_title",
        directory=str(repo),
        streaming=False,
    )

    response = await handle_chat_message(request, core=cast(Any, core))
    assert response["response"] == "ok"

    for _ in range(10):
        tasks = getattr(core, "_opencode_title_tasks", {})
        if not tasks:
            break
        await asyncio.sleep(0.01)

    assert summarize_calls == []


@pytest.mark.asyncio
async def test_rest_chat_auto_title_refresh_retries_until_snippets_exist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = tmp_path / "chat_repo_title_retry"
    repo.mkdir()
    summarize_calls: list[str] = []

    class _EventBus:
        def __init__(self) -> None:
            self.events: list[tuple[str, dict[str, Any]]] = []

        async def emit(self, event_type: str, data: dict[str, Any]) -> None:
            self.events.append((event_type, data))

    class _Core:
        def __init__(self) -> None:
            self.runtime_config = SimpleNamespace(
                workspace_root=str(tmp_path),
                project_root=str(tmp_path),
                active_root=str(tmp_path),
            )
            self._opencode_session_directories: dict[str, str] = {}
            self.event_bus = _EventBus()

        async def process(self, **kwargs):  # type: ignore[no-untyped-def]
            del kwargs
            return {"assistant_response": "ok", "action_results": []}

    async def _fake_summarize(
        _core: Any,
        session_id: str,
        *,
        provider_id: str | None = None,
        model_id: str | None = None,
        fallback_text: str | None = None,
    ) -> dict[str, Any]:
        del provider_id, model_id
        assert fallback_text == "ping"
        summarize_calls.append(session_id)
        if len(summarize_calls) == 1:
            return {
                "changed": False,
                "title": f"Session {session_id[-8:]}",
                "source": "heuristic",
                "snippet_count": 0,
                "info": {"id": session_id, "title": f"Session {session_id[-8:]}"},
            }
        return {
            "changed": True,
            "title": "Retried title",
            "source": "generated",
            "snippet_count": 1,
            "info": {"id": session_id, "title": "Retried title"},
        }

    def _fake_get_session_info(_core: Any, session_id: str) -> dict[str, Any]:
        return {"id": session_id, "title": f"Session {session_id[-8:]}"}

    def _fake_get_session_metadata_title(_core: Any, _session_id: str) -> str:
        return ""

    monkeypatch.setattr("penguin.web.routes.summarize_session_title", _fake_summarize)
    monkeypatch.setattr("penguin.web.routes.get_session_info", _fake_get_session_info)
    monkeypatch.setattr(
        "penguin.web.routes.get_session_metadata_title",
        _fake_get_session_metadata_title,
    )

    core = _Core()
    request = MessageRequest(
        text="ping",
        session_id="session_retry_12345678",
        conversation_id="session_retry_12345678",
        directory=str(repo),
        streaming=False,
    )

    response = await handle_chat_message(request, core=cast(Any, core))
    assert response["response"] == "ok"

    for _ in range(40):
        tasks = getattr(core, "_opencode_title_tasks", {})
        if not tasks:
            break
        await asyncio.sleep(0.01)

    assert summarize_calls == ["session_retry_12345678", "session_retry_12345678"]
    assert core.event_bus.events
    event_type, event_payload = core.event_bus.events[-1]
    assert event_type == "opencode_event"
    assert event_payload["type"] == "session.updated"


@pytest.mark.asyncio
async def test_rest_chat_queued_request_returns_aborted_when_cancelled(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "chat_repo_queued_cancel"
    repo.mkdir()

    class _Core:
        def __init__(self) -> None:
            self.runtime_config = SimpleNamespace(
                workspace_root=str(tmp_path),
                project_root=str(tmp_path),
                active_root=str(tmp_path),
            )
            self._opencode_session_directories: dict[str, str] = {}
            self._opencode_process_tasks: dict[str, set[asyncio.Task[Any]]] = {}
            self._opencode_request_gates = {
                "session_queued_cancel": asyncio.Lock()
            }

        async def process(self, **kwargs):  # type: ignore[no-untyped-def]
            del kwargs
            await asyncio.sleep(0.05)
            return {"assistant_response": "ok", "action_results": []}

    core = _Core()
    await core._opencode_request_gates["session_queued_cancel"].acquire()

    request = MessageRequest(
        text="queued cancel",
        session_id="session_queued_cancel",
        conversation_id="session_queued_cancel",
        directory=str(repo),
        streaming=False,
    )

    request_task = asyncio.create_task(
        handle_chat_message(request, core=cast(Any, core))
    )
    await asyncio.sleep(0.02)

    tracked = core._opencode_process_tasks.get("session_queued_cancel")
    assert isinstance(tracked, set)
    assert request_task in tracked

    request_task.cancel()
    response = await request_task

    assert response["aborted"] is True
    assert response["response"] == ""
    assert response["action_results"] == []

    tracked_after = core._opencode_process_tasks.get("session_queued_cancel")
    assert not tracked_after or request_task not in tracked_after

    core._opencode_request_gates["session_queued_cancel"].release()


@pytest.mark.asyncio
async def test_rest_chat_parts_forward_context_and_materialize_images(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "chat_repo_parts"
    repo.mkdir()
    readme = repo / "README.md"
    readme.write_text("hello", encoding="utf-8")
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
                "url": f"file://{readme.resolve()}",
                "source": {"type": "file", "path": "README.md"},
            },
        ],
    )

    response = await handle_chat_message(request, core=cast(Any, core))

    assert response["response"] == "ok"
    assert seen_kwargs["context_files"] == [str(readme.resolve())]
    image_paths = seen_kwargs["input_data"]["image_paths"]
    assert isinstance(image_paths, list)
    assert image_paths
    image_path = image_paths[0]
    assert isinstance(image_path, str)
    assert not image_path.startswith("data:")
    assert seen_kwargs["image_exists_during_process"] is True
    assert not Path(image_path).exists()


@pytest.mark.asyncio
async def test_rest_chat_parts_fallback_to_file_url_for_context_file(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "chat_repo_parts_url_fallback"
    repo.mkdir()
    readme = repo / "README.md"
    readme.write_text("hello", encoding="utf-8")
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
        text="summarize selected file",
        session_id="session_parts_url_fallback",
        directory=str(repo),
        streaming=False,
        parts=[
            {
                "type": "file",
                "mime": "text/plain",
                "url": f"file://{readme.resolve()}",
                "source": {"type": "file", "path": "missing.txt"},
            }
        ],
    )

    response = await handle_chat_message(request, core=cast(Any, core))

    assert response["response"] == "ok"
    assert seen_kwargs["context_files"] == [str(readme.resolve())]


@pytest.mark.asyncio
async def test_rest_chat_normalizes_explicit_context_files_against_bound_directory(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "chat_repo_context_files_normalized"
    repo.mkdir()
    readme = repo / "README.md"
    readme.write_text("hello", encoding="utf-8")
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
        text="summarize",
        session_id="session_context_files_normalized",
        directory=str(repo),
        streaming=False,
        context_files=["README.md"],
    )

    response = await handle_chat_message(request, core=cast(Any, core))

    assert response["response"] == "ok"
    assert seen_kwargs["context_files"] == [str(readme.resolve())]


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
        parts=[
            {
                "type": "file",
                "mime": "image/png",
                "url": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAOQOt9kAAAAASUVORK5CYII=",
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
async def test_rest_chat_extracts_inline_file_references_as_context_files(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "chat_repo_inline_context"
    repo.mkdir()
    readme = repo / "README.md"
    readme.write_text("hello", encoding="utf-8")
    docs_dir = repo / "docs"
    docs_dir.mkdir()
    guide = docs_dir / "guide.md"
    guide.write_text("guide", encoding="utf-8")

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
        text="Check @README.md and @docs/guide.md.",
        session_id="session_inline_context",
        directory=str(repo),
        streaming=False,
    )

    response = await handle_chat_message(request, core=cast(Any, core))

    assert response["response"] == "ok"
    assert seen_kwargs["context_files"] == [
        str(readme.resolve()),
        str(guide.resolve()),
    ]


@pytest.mark.asyncio
async def test_rest_chat_inline_file_references_ignore_non_file_mentions(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "chat_repo_inline_filters"
    repo.mkdir()
    ignored = repo / "ignored.md"
    ignored.write_text("ignore me", encoding="utf-8")
    included = repo / "included.md"
    included.write_text("include me", encoding="utf-8")

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
        text=(
            "Ignore `@ignored.md` and user@example.com and @missing.md, "
            "but include @included.md"
        ),
        session_id="session_inline_filters",
        directory=str(repo),
        streaming=False,
        context_files=["EXPLICIT.md"],
    )

    response = await handle_chat_message(request, core=cast(Any, core))

    assert response["response"] == "ok"
    assert seen_kwargs["context_files"] == ["EXPLICIT.md", str(included.resolve())]


@pytest.mark.asyncio
async def test_rest_chat_inline_file_references_dedupe_equivalent_mentions(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "chat_repo_inline_dedupe"
    repo.mkdir()
    file_path = repo / "notes.md"
    file_path.write_text("notes", encoding="utf-8")

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
        text=(
            "Use @notes.md and @notes.md, then @./notes.md#L10 and @notes.md?start=10."
        ),
        session_id="session_inline_dedupe",
        directory=str(repo),
        streaming=False,
    )

    response = await handle_chat_message(request, core=cast(Any, core))

    assert response["response"] == "ok"
    assert seen_kwargs["context_files"] == [str(file_path.resolve())]


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
