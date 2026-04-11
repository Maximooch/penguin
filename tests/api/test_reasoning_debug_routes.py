from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

from fastapi import FastAPI
from fastapi.testclient import TestClient

from penguin.web import routes as routes_module


class _Core:
    def __init__(self, workspace: Path) -> None:
        root = str(workspace)
        self.runtime_config = SimpleNamespace(
            workspace_root=root,
            project_root=root,
            active_root=root,
        )
        self._reasoning_debug_snapshots: dict[str, dict[str, Any]] = {}


def _build_client(core: _Core) -> TestClient:
    cast(Any, routes_module.router).core = cast(Any, core)
    app = FastAPI()
    app.include_router(routes_module.router)
    return TestClient(app)


def test_message_request_defaults_include_reasoning_true() -> None:
    request = routes_module.MessageRequest(text="hello")

    assert request.include_reasoning is True
    assert routes_module._resolve_include_reasoning(request.include_reasoning) is True
    assert routes_module._resolve_include_reasoning(False) is False


def test_reasoning_visibility_note_when_tokens_exist_without_summary() -> None:
    note = routes_module._build_reasoning_visibility_note(
        include_reasoning=True,
        reasoning_text="",
        reasoning_payload={"effort": "xhigh"},
        usage={"reasoning_tokens": 158},
    )

    assert (
        note
        == "Reasoning effort applied, but provider returned no visible reasoning summary."
    )


def test_reasoning_debug_endpoint_returns_persisted_snapshot(tmp_path: Path) -> None:
    core = _Core(tmp_path)
    core._reasoning_debug_snapshots["session-1"] = {
        "session_id": "session-1",
        "model": "gpt-5.4",
        "handler_debug": {"event_types": ["response.completed"]},
    }

    with _build_client(core) as client:
        response = client.get("/api/v1/session/session-1/reasoning-debug")

    assert response.status_code == 200
    assert response.json()["handler_debug"]["event_types"] == ["response.completed"]
