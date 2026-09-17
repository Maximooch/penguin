"""Contract tests for Penguin's pinned OpenCode 2 compatibility slice."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from penguin.security.approval import get_approval_manager
from penguin.security.question import get_question_manager
from penguin.system.state import Session
from penguin.web import opencode_v2_routes as routes
from penguin.web.services.opencode_events import emit_opencode_event
from penguin.web.services.opencode_v2 import (
    UPSTREAM_V2_COMMIT,
    active_sessions_payload,
    create_session_payload,
    event_payload,
    prompt_payload,
)
from penguin.web.services.opencode_v2_interactions import (
    form_id_for_question,
    permission_id_for_approval,
)
from penguin.web.services.session_view import TRANSCRIPT_KEY


class _EventBus:
    def __init__(self) -> None:
        self.handlers: dict[str, list[Any]] = {}
        self.events: list[tuple[str, dict[str, Any]]] = []

    def subscribe(self, event_type: str, handler: Any) -> None:
        self.handlers.setdefault(event_type, []).append(handler)

    def unsubscribe(self, event_type: str, handler: Any) -> None:
        self.handlers.get(event_type, []).remove(handler)

    async def emit(self, event_type: str, data: dict[str, Any]) -> None:
        self.events.append((event_type, data))
        for handler in list(self.handlers.get(event_type, [])):
            handler(event_type, data)


class _Manager:
    def __init__(self) -> None:
        self.sessions: dict[str, tuple[Session, bool]] = {}
        self.session_index: dict[str, dict[str, Any]] = {}
        self.current_session: Session | None = None

    def create_session(self) -> Session:
        session = Session()
        self.sessions[session.id] = (session, True)
        self.current_session = session
        self.save_session(session)
        return session

    def load_session(self, session_id: str) -> Session | None:
        row = self.sessions.get(session_id)
        return row[0] if row else None

    def mark_session_modified(self, session_id: str) -> None:
        session = self.load_session(session_id)
        if session:
            self.sessions[session_id] = (session, True)

    def save_session(self, session: Session) -> bool:
        self.sessions[session.id] = (session, False)
        self.session_index[session.id] = {
            "created_at": session.created_at,
            "last_active": session.last_active,
            "message_count": len(session.messages),
            "title": session.metadata.get("title", ""),
            "directory": session.metadata.get("directory", ""),
        }
        return True

    def delete_session(self, session_id: str) -> bool:
        existed = session_id in self.sessions
        self.sessions.pop(session_id, None)
        self.session_index.pop(session_id, None)
        return existed


class _Core:
    def __init__(self, workspace: Path) -> None:
        manager = _Manager()
        self.runtime_config = SimpleNamespace(
            workspace_root=str(workspace),
            project_root=str(workspace),
            active_root=str(workspace),
        )
        self.model_config = SimpleNamespace(provider="openai", model="gpt-5")
        self.conversation_manager = SimpleNamespace(
            session_manager=manager,
            current_agent_id="default",
            agent_session_managers={"default": manager},
        )
        self.event_bus = _EventBus()
        self._opencode_session_directories: dict[str, str] = {}
        self._opencode_stream_states: dict[str, dict[str, Any]] = {}
        self.abort_session = AsyncMock(return_value=True)


def _client(core: _Core) -> TestClient:
    routes.router.core = cast("Any", core)
    app = FastAPI()
    app.include_router(routes.router)
    app.add_exception_handler(routes.OpenCodeV2HTTPError, routes.handle_http_error)
    return TestClient(app)


def _fixture() -> dict[str, Any]:
    path = (
        Path(__file__).parents[1] / "fixtures" / "opencode_v2" / "core_contracts.json"
    )
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def _reset_interaction_managers() -> Any:
    approval = get_approval_manager()
    question = get_question_manager()
    approval.reset()
    question.reset()
    yield
    approval.reset()
    question.reset()


def test_pinned_fixture_matches_implementation() -> None:
    assert _fixture()["upstream"]["commit"] == UPSTREAM_V2_COMMIT


def test_health_and_deep_location_contract(tmp_path: Path) -> None:
    core = _Core(tmp_path)
    with _client(core) as client:
        health = client.get("/api/health")
        location = client.get(
            "/api/location",
            params={"location[directory]": str(tmp_path)},
        )

    assert health.status_code == 200
    assert set(_fixture()["health_required"]) <= health.json().keys()
    assert health.json()["healthy"] is True
    assert health.json()["pid"] > 0
    assert location.status_code == 200
    assert location.json() == {
        "directory": str(tmp_path.resolve()),
        "project": {
            "id": "penguin",
            "directory": str(tmp_path.resolve()),
            "canonical": str(tmp_path.resolve()),
        },
    }


def test_filesystem_vcs_and_project_boot_contract(tmp_path: Path) -> None:
    (tmp_path / "alpha").mkdir()
    (tmp_path / "note.txt").write_text("hello", encoding="utf-8")
    core = _Core(tmp_path)
    params = {"location[directory]": str(tmp_path)}

    with _client(core) as client:
        filesystem = client.get("/api/fs/list", params=params)
        vcs = client.get("/api/vcs", params=params)
        current = client.get("/api/project/current", params=params)
        projects = client.get("/api/project")
        escaped = client.get("/api/fs/list", params={**params, "path": ".."})

    expected_location = {
        "directory": str(tmp_path.resolve()),
        "project": {
            "id": "penguin",
            "directory": str(tmp_path.resolve()),
            "canonical": str(tmp_path.resolve()),
        },
    }
    assert filesystem.status_code == 200
    assert filesystem.json() == {
        "location": expected_location,
        "data": [
            {"path": "alpha/", "type": "directory"},
            {"path": "note.txt", "type": "file"},
        ],
    }
    assert vcs.status_code == 200
    assert vcs.json() == {
        "location": expected_location,
        "data": {"branch": {}},
    }
    assert current.json() == {
        "id": "penguin",
        "directory": str(tmp_path.resolve()),
        "canonical": str(tmp_path.resolve()),
    }
    project = projects.json()[0]
    assert project["id"] == "penguin"
    assert project["canonical"] == str(tmp_path.resolve())
    assert project["name"] == tmp_path.name
    assert project["sandboxes"] == []
    assert set(project["time"]) == {"created", "updated"}
    assert escaped.status_code == 400
    assert escaped.json() == {
        "_tag": "InvalidRequestError",
        "message": "path escapes the requested location",
    }


def test_location_catalogs_are_complete_and_exactly_shaped(tmp_path: Path) -> None:
    core = _Core(tmp_path)
    params = {
        "location[directory]": str(tmp_path),
        "location[workspace]": "workspace_one",
    }
    empty_paths = [
        "/api/command",
        "/api/integration",
        "/api/mcp",
        "/api/reference",
        "/api/skill",
        "/api/shell",
        "/api/form/request",
    ]

    with _client(core) as client:
        agents = client.get("/api/agent", params=params)
        models = client.get("/api/model", params=params)
        providers = client.get("/api/provider", params=params)
        empty = {path: client.get(path, params=params) for path in empty_paths}
        resources = client.get("/api/mcp/resource", params=params)
        migration = client.get("/api/experimental/migration/v1")

    expected_location = {
        "directory": str(tmp_path.resolve()),
        "workspaceID": "workspace_one",
        "project": {
            "id": "penguin",
            "directory": str(tmp_path.resolve()),
            "canonical": str(tmp_path.resolve()),
        },
    }
    for response in empty.values():
        assert response.status_code == 200
        assert response.json() == {"location": expected_location, "data": []}

    model = models.json()["data"][0]
    assert model == {
        "id": "gpt-5",
        "modelID": "gpt-5",
        "providerID": "openai",
        "name": "gpt-5",
        "capabilities": {
            "tools": True,
            "input": ["text"],
            "output": ["text"],
        },
        "variants": [],
        "time": {"released": 0},
        "cost": [],
        "status": "active",
        "enabled": True,
        "limit": {"context": 128000, "output": 8192},
    }
    assert providers.json() == {
        "location": expected_location,
        "data": [{"id": "openai", "name": "OpenAI", "package": ""}],
    }
    assert agents.json() == {
        "location": expected_location,
        "data": [
            {
                "id": agent_id,
                "name": name,
                "model": {"providerID": "openai", "id": "gpt-5"},
                "request": {"settings": {}, "headers": {}, "body": {}},
                "mode": "primary",
                "hidden": False,
                "permissions": [],
            }
            for agent_id, name in (("build", "Build"), ("plan", "Plan"))
        ],
    }
    assert resources.json() == {
        "location": expected_location,
        "data": {"resources": [], "templates": []},
    }
    assert migration.json() == {"status": "completed"}


def test_session_permission_and_form_hydration_are_empty(tmp_path: Path) -> None:
    core = _Core(tmp_path)
    with _client(core) as client:
        session_id = client.post("/api/session", json={}).json()["data"]["id"]
        permissions = client.get(f"/api/session/{session_id}/permission")
        forms = client.get(f"/api/session/{session_id}/form")
        missing_permissions = client.get("/api/session/session_missing/permission")
        missing_forms = client.get("/api/session/session_missing/form")

    assert permissions.json() == {"data": []}
    assert forms.json() == {"data": []}
    assert missing_permissions.status_code == 404
    assert missing_permissions.json()["_tag"] == "SessionNotFoundError"
    assert missing_forms.status_code == 404
    assert missing_forms.json()["_tag"] == "SessionNotFoundError"


def test_pending_interactions_rehydrate_from_managers_after_disconnect(
    tmp_path: Path,
) -> None:
    core = _Core(tmp_path)
    with _client(core) as client:
        session_id = client.post("/api/session", json={}).json()["data"]["id"]

    approval = get_approval_manager().create_request(
        tool_name="execute_command",
        operation="process.execute",
        resource="pytest -q",
        reason="Run tests",
        session_id=session_id,
    )
    question = get_question_manager().create_request(
        session_id=session_id,
        questions=[
            {
                "question": "Run the suite?",
                "header": "Tests",
                "options": [{"label": "Run", "description": "Run now"}],
            }
        ],
    )

    with _client(core) as reconnected:
        permissions = reconnected.get(f"/api/session/{session_id}/permission")
        forms = reconnected.get(f"/api/session/{session_id}/form")

    assert [item["id"] for item in permissions.json()["data"]] == [
        permission_id_for_approval(approval.id)
    ]
    assert [item["id"] for item in forms.json()["data"]] == [
        form_id_for_question(question.id)
    ]


def test_permission_list_get_reply_reject_and_session_isolation(
    tmp_path: Path,
) -> None:
    core = _Core(tmp_path)
    manager = get_approval_manager()
    with _client(core) as client:
        first_session = client.post("/api/session", json={}).json()["data"]["id"]
        second_session = client.post("/api/session", json={}).json()["data"]["id"]
        first = manager.create_request(
            tool_name="write_to_file",
            operation="filesystem.write",
            resource="src/app.py",
            reason="Write requires approval",
            session_id=first_session,
            context={
                "tool_input": {"path": "src/app.py"},
                "tool": {"messageID": "msg_1", "callID": "call_1"},
            },
        )
        manager.create_request(
            tool_name="execute_command",
            operation="process.execute",
            resource="pytest -q",
            reason="Command requires approval",
            session_id=second_session,
        )
        permission_id = permission_id_for_approval(first.id)

        listed = client.get(f"/api/session/{first_session}/permission")
        fetched = client.get(f"/api/session/{first_session}/permission/{permission_id}")
        global_list = client.get(
            "/api/permission/request",
            params={"location[directory]": str(tmp_path)},
        )
        wrong_session = client.get(
            f"/api/session/{second_session}/permission/{permission_id}"
        )
        malformed = client.post(
            f"/api/session/{first_session}/permission/{permission_id}/reply",
            json={"reply": "maybe"},
        )
        replied = client.post(
            f"/api/session/{first_session}/permission/{permission_id}/reply",
            json={"reply": "once"},
        )

        rejected_request = manager.create_request(
            tool_name="execute_command",
            operation="process.execute",
            resource="rm build.txt",
            reason="Delete generated output",
            session_id=first_session,
        )
        rejected = client.post(
            f"/api/session/{first_session}/permission/"
            f"{permission_id_for_approval(rejected_request.id)}/reply",
            json={"reply": "reject", "message": "Keep the artifact"},
        )

    expected = {
        "id": permission_id,
        "sessionID": first_session,
        "action": "edit",
        "resources": ["src/app.py"],
        "save": ["src/app.py"],
        "metadata": {
            "reason": "Write requires approval",
            "operation": "filesystem.write",
            "tool_name": "write_to_file",
            "resource": "src/app.py",
            "path": "src/app.py",
        },
        "source": {"type": "tool", "messageID": "msg_1", "id": "call_1"},
    }
    assert listed.json() == {"data": [expected]}
    assert fetched.json() == {"data": expected}
    assert len(global_list.json()["data"]) == 2
    assert {
        item["sessionID"]: item["action"] for item in global_list.json()["data"]
    } == {first_session: "edit", second_session: "shell"}
    assert wrong_session.status_code == 404
    assert wrong_session.json()["_tag"] == "PermissionNotFoundError"
    assert malformed.status_code == 400
    assert malformed.json() == {
        "_tag": "InvalidRequestError",
        "message": "reply must be one of: once, always, reject",
    }
    assert replied.status_code == 204
    assert manager.get_request(first.id).status.value == "approved"
    assert rejected.status_code == 204
    resolved_rejection = manager.get_request(rejected_request.id)
    assert resolved_rejection is not None
    assert resolved_rejection.status.value == "denied"
    assert resolved_rejection.context["message"] == "Keep the artifact"


def test_permission_events_project_exact_v2_request_and_reply() -> None:
    asked = event_payload(
        {
            "id": "legacy-permission-asked",
            "time": 10,
            "type": "permission.asked",
            "properties": {
                "id": "legacy_permission",
                "sessionID": "session_one",
                "permission": "bash",
                "patterns": ["pytest -q"],
                "always": ["pytest -q"],
                "metadata": {"reason": "Run tests"},
                "tool": {"messageID": "msg_1", "callID": "call_1"},
            },
        }
    )
    replied = event_payload(
        {
            "id": "legacy-permission-replied",
            "time": 11,
            "type": "permission.replied",
            "properties": {
                "sessionID": "session_one",
                "requestID": "legacy_permission",
                "reply": "always",
            },
        }
    )

    assert asked is not None
    assert asked["type"] == "permission.asked"
    assert asked["data"] == {
        "id": "per_legacy_permission",
        "sessionID": "session_one",
        "action": "shell",
        "resources": ["pytest -q"],
        "save": ["pytest -q"],
        "metadata": {"reason": "Run tests"},
        "source": {"type": "tool", "messageID": "msg_1", "id": "call_1"},
    }
    assert "durable" not in asked
    assert replied is not None
    assert replied["type"] == "permission.replied"
    assert replied["data"] == {
        "sessionID": "session_one",
        "requestID": "per_legacy_permission",
        "reply": "always",
    }

    delegated = event_payload(
        {
            "id": "legacy-permission-task",
            "type": "permission.asked",
            "properties": {
                "id": "legacy_task_permission",
                "sessionID": "session_one",
                "permission": "task",
                "patterns": ["explore"],
            },
        }
    )
    assert delegated is not None
    assert delegated["data"]["action"] == "subagent"


def test_question_forms_list_get_reply_and_validate_ordered_answers(
    tmp_path: Path,
) -> None:
    core = _Core(tmp_path)
    manager = get_question_manager()
    with _client(core) as client:
        first_session = client.post("/api/session", json={}).json()["data"]["id"]
        second_session = client.post("/api/session", json={}).json()["data"]["id"]
        request = manager.create_request(
            session_id=first_session,
            questions=[
                {
                    "question": "Proceed with migration?",
                    "header": "Migration",
                    "options": [
                        {"label": "Yes", "description": "Continue"},
                        {"label": "No", "description": "Stop"},
                    ],
                    "custom": False,
                },
                {
                    "question": "Which checks should run?",
                    "header": "Checks",
                    "options": [
                        {"label": "Unit", "description": "Unit tests"},
                        {"label": "API", "description": "API tests"},
                    ],
                    "multiple": True,
                    "custom": False,
                },
            ],
        )
        form_id = form_id_for_question(request.id)

        listed = client.get(f"/api/session/{first_session}/form")
        fetched = client.get(f"/api/session/{first_session}/form/{form_id}")
        global_list = client.get(
            "/api/form/request",
            params={"location[directory]": str(tmp_path)},
        )
        wrong_session = client.get(f"/api/session/{second_session}/form/{form_id}")
        malformed = client.post(
            f"/api/session/{first_session}/form/{form_id}/reply",
            json={"answer": {"question_0": "Yes"}},
        )
        replied = client.post(
            f"/api/session/{first_session}/form/{form_id}/reply",
            json={
                "answer": {
                    "question_1": ["API", "Unit"],
                    "question_0": "Yes",
                }
            },
        )
        retained = client.get(f"/api/session/{first_session}/form/{form_id}")
        pending_after = client.get(f"/api/session/{first_session}/form")
        repeated = client.post(
            f"/api/session/{first_session}/form/{form_id}/reply",
            json={
                "answer": {
                    "question_0": "Yes",
                    "question_1": ["Unit"],
                }
            },
        )

    form = listed.json()["data"][0]
    assert form["id"] == form_id
    assert form["sessionID"] == first_session
    assert form["title"] == "Questions"
    assert form["fields"] == [
        {
            "key": "question_0",
            "title": "Migration",
            "description": "Proceed with migration?",
            "required": True,
            "options": [
                {"value": "Yes", "label": "Yes", "description": "Continue"},
                {"value": "No", "label": "No", "description": "Stop"},
            ],
            "custom": False,
            "type": "string",
        },
        {
            "key": "question_1",
            "title": "Checks",
            "description": "Which checks should run?",
            "required": True,
            "options": [
                {"value": "Unit", "label": "Unit", "description": "Unit tests"},
                {"value": "API", "label": "API", "description": "API tests"},
            ],
            "custom": False,
            "type": "multiselect",
        },
    ]
    assert fetched.json() == {"data": form}
    assert global_list.json()["data"] == [form]
    assert wrong_session.status_code == 404
    assert wrong_session.json()["_tag"] == "FormNotFoundError"
    assert malformed.status_code == 400
    assert malformed.json() == {
        "_tag": "FormInvalidAnswerError",
        "id": form_id,
        "message": "missing fields: question_1",
    }
    assert replied.status_code == 204
    resolved = manager.get_request(request.id)
    assert resolved is not None
    assert resolved.status.value == "answered"
    assert resolved.answers == [["Yes"], ["API", "Unit"]]
    assert retained.json() == {"data": form}
    assert pending_after.json() == {"data": []}
    assert repeated.status_code == 409
    assert repeated.json()["_tag"] == "FormAlreadySettledError"


def test_question_form_cancel_is_session_scoped_and_idempotently_terminal(
    tmp_path: Path,
) -> None:
    core = _Core(tmp_path)
    manager = get_question_manager()
    with _client(core) as client:
        owner = client.post("/api/session", json={}).json()["data"]["id"]
        other = client.post("/api/session", json={}).json()["data"]["id"]
        request = manager.create_request(
            session_id=owner,
            questions=[
                {
                    "question": "Apply patch?",
                    "header": "Patch",
                    "options": [
                        {"label": "Apply", "description": "Apply now"},
                        {"label": "Skip", "description": "Skip it"},
                    ],
                }
            ],
        )
        form_id = form_id_for_question(request.id)

        wrong_session = client.post(f"/api/session/{other}/form/{form_id}/cancel")
        cancelled = client.post(f"/api/session/{owner}/form/{form_id}/cancel")
        repeated = client.post(f"/api/session/{owner}/form/{form_id}/cancel")

    assert wrong_session.status_code == 404
    assert cancelled.status_code == 204
    resolved = manager.get_request(request.id)
    assert resolved is not None
    assert resolved.status.value == "rejected"
    assert repeated.status_code == 409
    assert repeated.json()["_tag"] == "FormAlreadySettledError"


def test_question_events_project_to_created_replied_and_cancelled_forms() -> None:
    manager = get_question_manager()
    request = manager.create_request(
        session_id="session_form_events",
        questions=[
            {
                "question": "Pick one",
                "header": "Pick",
                "options": [
                    {"label": "A", "description": "First"},
                    {"label": "B", "description": "Second"},
                ],
                "custom": False,
            }
        ],
    )
    created = event_payload(
        {
            "id": "legacy-question-created",
            "type": "question.asked",
            "properties": request.to_dict(),
        }
    )
    manager.reply(request.id, [["A"]])
    replied = event_payload(
        {
            "id": "legacy-question-replied",
            "type": "question.replied",
            "properties": {
                "sessionID": request.session_id,
                "requestID": request.id,
                "answers": [["A"]],
            },
        }
    )

    cancelled_request = manager.create_request(
        session_id="session_form_events",
        questions=[
            {
                "question": "Continue?",
                "header": "Continue",
                "options": [{"label": "Yes", "description": "Continue"}],
            }
        ],
    )
    manager.reject(cancelled_request.id)
    cancelled = event_payload(
        {
            "id": "legacy-question-cancelled",
            "type": "question.rejected",
            "properties": {
                "sessionID": cancelled_request.session_id,
                "requestID": cancelled_request.id,
            },
        }
    )

    assert created is not None
    assert created["type"] == "form.created"
    form = created["data"]["form"]
    assert form["id"] == form_id_for_question(request.id)
    assert form["fields"][0]["key"] == "question_0"
    assert replied is not None
    assert replied["type"] == "form.replied"
    assert replied["data"] == {
        "id": form_id_for_question(request.id),
        "sessionID": request.session_id,
        "answer": {"question_0": "A"},
    }
    assert cancelled is not None
    assert cancelled["type"] == "form.cancelled"
    assert cancelled["data"] == {
        "id": form_id_for_question(cancelled_request.id),
        "sessionID": cancelled_request.session_id,
    }
    assert "durable" not in created
    assert "durable" not in replied
    assert "durable" not in cancelled


def test_malformed_question_request_is_not_exposed_as_a_v2_form(
    tmp_path: Path,
) -> None:
    core = _Core(tmp_path)
    manager = get_question_manager()
    with _client(core) as client:
        session_id = client.post("/api/session", json={}).json()["data"]["id"]
        malformed = manager.create_request(session_id=session_id, questions=[])
        listed = client.get(f"/api/session/{session_id}/form")
        fetched = client.get(
            f"/api/session/{session_id}/form/{form_id_for_question(malformed.id)}"
        )

    assert listed.json() == {"data": []}
    assert fetched.status_code == 404
    assert (
        event_payload(
            {
                "type": "question.asked",
                "properties": malformed.to_dict(),
            }
        )
        is None
    )


def test_session_crud_selection_and_exact_error_shape(tmp_path: Path) -> None:
    core = _Core(tmp_path)
    with _client(core) as client:
        created_response = client.post(
            "/api/session",
            json={
                "title": "V2 session",
                "agent": "build",
                "model": {"providerID": "openai", "id": "gpt-5"},
                "location": {"directory": str(tmp_path)},
            },
        )
        created = created_response.json()["data"]
        session_id = created["id"]

        listed = client.get("/api/session", params={"order": "desc"})
        fetched = client.get(f"/api/session/{session_id}")
        renamed = client.post(
            f"/api/session/{session_id}/rename", json={"title": "Renamed"}
        )
        switched_agent = client.post(
            f"/api/session/{session_id}/agent", json={"agent": "plan"}
        )
        switched_model = client.post(
            f"/api/session/{session_id}/model",
            json={
                "model": {
                    "providerID": "anthropic",
                    "id": "claude-sonnet",
                    "variant": "high",
                }
            },
        )
        selected = client.get(f"/api/session/{session_id}").json()["data"]
        removed = client.delete(f"/api/session/{session_id}")
        missing = client.get(f"/api/session/{session_id}")

    assert created_response.status_code == 200
    assert set(_fixture()["session_required"]) <= created.keys()
    assert created["agent"] == "build"
    assert listed.json()["data"][0]["id"] == session_id
    assert listed.json()["cursor"] == {}
    assert fetched.json()["data"] == created
    assert renamed.status_code == 204
    assert switched_agent.status_code == 204
    assert switched_model.status_code == 204
    assert selected["title"] == "Renamed"
    assert selected["agent"] == "plan"
    assert selected["model"] == {
        "providerID": "anthropic",
        "id": "claude-sonnet",
        "variant": "high",
    }
    assert removed.status_code == 204
    assert missing.status_code == 404
    assert missing.json() == {
        "_tag": "SessionNotFoundError",
        "message": f"Session not found: {session_id}",
        "sessionID": session_id,
    }
    emitted_types = [
        event["type"]
        for channel, event in core.event_bus.events
        if channel == "opencode_event"
    ]
    assert emitted_types == [
        "session.created",
        "session.updated",
        "session.agent.selected",
        "session.model.selected",
        "session.deleted",
    ]


def test_delete_parent_removes_descendants_children_first(tmp_path: Path) -> None:
    core = _Core(tmp_path)
    with _client(core) as client:
        parent = client.post("/api/session", json={}).json()["data"]
        child = client.post("/api/session", json={"parentID": parent["id"]}).json()[
            "data"
        ]
        grandchild = client.post("/api/session", json={"parentID": child["id"]}).json()[
            "data"
        ]
        unrelated = client.post("/api/session", json={}).json()["data"]

        removed = client.delete(f"/api/session/{parent['id']}")
        remaining = client.get("/api/session").json()["data"]

    assert child["parentID"] == parent["id"]
    assert grandchild["parentID"] == child["id"]
    assert removed.status_code == 204
    assert [item["id"] for item in remaining] == [unrelated["id"]]
    deleted = [
        event["properties"]["info"]["id"]
        for channel, event in core.event_bus.events
        if channel == "opencode_event" and event["type"] == "session.deleted"
    ]
    assert deleted == [grandchild["id"], child["id"], parent["id"]]


@pytest.mark.asyncio
async def test_delete_active_session_interrupts_and_awaits_its_task(
    tmp_path: Path,
) -> None:
    core = _Core(tmp_path)
    created = create_session_payload(core, {}, default_directory=str(tmp_path))
    session_id = created["id"]
    settled = asyncio.Event()

    async def worker() -> None:
        try:
            await asyncio.Event().wait()
        finally:
            settled.set()

    task = asyncio.create_task(worker())
    await asyncio.sleep(0)
    core._opencode_active_requests = {session_id: 1}
    core._opencode_process_tasks = {session_id: {task}}

    async def abort(active_session_id: str) -> bool:
        assert active_session_id == session_id
        task.cancel()
        return True

    core.abort_session = abort
    response = await routes.session_remove(session_id, core=cast("Any", core))

    assert response.status_code == 204
    assert settled.is_set()
    assert task.done()
    assert core.conversation_manager.session_manager.load_session(session_id) is None
    emitted = [
        event["type"]
        for channel, event in core.event_bus.events
        if channel == "opencode_event"
    ]
    assert emitted[-2:] == ["session.execution.interrupted", "session.deleted"]


@pytest.mark.asyncio
async def test_delete_reservation_rejects_prompt_and_new_child(
    tmp_path: Path,
) -> None:
    core = _Core(tmp_path)
    ancestor = create_session_payload(core, {}, default_directory=str(tmp_path))
    parent = create_session_payload(
        core,
        {"parentID": ancestor["id"]},
        default_directory=str(tmp_path),
    )
    session_id = parent["id"]
    core._opencode_active_requests = {session_id: 1}
    interrupt_started = asyncio.Event()
    release_interrupt = asyncio.Event()

    async def abort(active_session_id: str) -> bool:
        assert active_session_id == session_id
        interrupt_started.set()
        await release_interrupt.wait()
        return True

    core.abort_session = abort
    deleting = asyncio.create_task(
        routes.session_remove(session_id, core=cast("Any", core))
    )
    await asyncio.wait_for(interrupt_started.wait(), timeout=1)

    with pytest.raises(routes.OpenCodeV2HTTPError) as prompt_error:
        await routes.session_prompt(
            session_id,
            {"text": "too late"},
            core=cast("Any", core),
        )
    with pytest.raises(routes.OpenCodeV2HTTPError) as child_error:
        await routes.session_create(
            {"parentID": session_id},
            core=cast("Any", core),
        )
    with pytest.raises(routes.OpenCodeV2HTTPError) as ancestor_error:
        await routes.session_remove(ancestor["id"], core=cast("Any", core))

    assert prompt_error.value.status_code == 409
    assert prompt_error.value.payload["_tag"] == "SessionBusyError"
    assert child_error.value.status_code == 409
    assert child_error.value.payload["_tag"] == "SessionBusyError"
    assert ancestor_error.value.status_code == 409
    assert ancestor_error.value.payload["_tag"] == "SessionBusyError"

    release_interrupt.set()
    response = await asyncio.wait_for(deleting, timeout=1)
    assert response.status_code == 204
    assert routes._deleting_sessions(cast("Any", core)) == set()
    assert set(core.conversation_manager.session_manager.sessions) == {ancestor["id"]}


def test_message_projection_returns_flat_v2_union(tmp_path: Path) -> None:
    core = _Core(tmp_path)
    with _client(core) as client:
        session_id = client.post("/api/session", json={}).json()["data"]["id"]
        session = core.conversation_manager.session_manager.load_session(session_id)
        assert session is not None
        session.metadata[TRANSCRIPT_KEY] = {
            "order": ["msg_user", "msg_assistant"],
            "messages": {
                "msg_user": {
                    "info": {
                        "id": "msg_user",
                        "sessionID": session_id,
                        "role": "user",
                        "time": {"created": 10},
                    },
                    "part_order": ["part_user"],
                    "parts": {
                        "part_user": {
                            "id": "part_user",
                            "type": "text",
                            "text": "hello",
                        }
                    },
                },
                "msg_assistant": {
                    "info": {
                        "id": "msg_assistant",
                        "sessionID": session_id,
                        "role": "assistant",
                        "agent": "build",
                        "providerID": "openai",
                        "modelID": "gpt-5",
                        "time": {"created": 20, "completed": 30},
                    },
                    "part_order": ["part_assistant"],
                    "parts": {
                        "part_assistant": {
                            "id": "part_assistant",
                            "type": "text",
                            "text": "hi",
                        }
                    },
                },
            },
        }

        response = client.get(
            f"/api/session/{session_id}/message",
            params={"limit": 200, "order": "desc"},
        )

    assert response.status_code == 200
    assistant, user = response.json()["data"]
    assert assistant["type"] == "assistant"
    assert assistant["content"] == [{"type": "text", "text": "hi"}]
    assert assistant["model"] == {"providerID": "openai", "id": "gpt-5"}
    assert user == {
        "id": "msg_user",
        "type": "user",
        "text": "hello",
        "time": {"created": 10},
    }


def test_prompt_admission_reuses_background_chat_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    core = _Core(tmp_path)
    runner = AsyncMock()
    monkeypatch.setattr(routes, "_run_prompt", runner)
    with _client(core) as client:
        session_id = client.post("/api/session", json={"agent": "build"}).json()[
            "data"
        ]["id"]
        response = client.post(
            f"/api/session/{session_id}/prompt",
            json={"id": "msg_client", "text": "ship it", "delivery": "steer"},
        )

    assert response.status_code == 200
    assert response.json()["data"] == {
        "id": "msg_client",
        "sessionID": session_id,
        "timeCreated": response.json()["data"]["timeCreated"],
        "type": "user",
        "data": {"text": "ship it"},
        "delivery": "steer",
    }
    runner.assert_awaited_once()
    request_payload = runner.await_args.args[1]
    assert request_payload["session_id"] == session_id
    assert request_payload["client_message_id"] == "msg_client"


def test_prompt_rejects_queue_and_busy_steer_without_scheduling(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    core = _Core(tmp_path)
    runner = AsyncMock()
    monkeypatch.setattr(routes, "_run_prompt", runner)
    with _client(core) as client:
        session_id = client.post("/api/session", json={}).json()["data"]["id"]
        core._opencode_active_requests = {session_id: 1}
        queued = client.post(
            f"/api/session/{session_id}/prompt",
            json={"text": "later", "delivery": "queue"},
        )
        busy = client.post(
            f"/api/session/{session_id}/prompt",
            json={"text": "now", "delivery": "steer"},
        )

    assert queued.status_code == 400
    assert queued.json() == {
        "_tag": "InvalidRequestError",
        "message": "queue delivery is not supported yet",
    }
    assert busy.status_code == 409
    assert busy.json() == {
        "_tag": "SessionBusyError",
        "sessionID": session_id,
        "message": f"Session is already running: {session_id}",
    }
    runner.assert_not_awaited()


@pytest.mark.asyncio
async def test_prompt_reservation_rejects_a_concurrent_second_post(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    core = _Core(tmp_path)
    created = create_session_payload(core, {}, default_directory=str(tmp_path))
    session_id = created["id"]
    started = asyncio.Event()
    release = asyncio.Event()
    requests: list[Any] = []

    async def blocking_chat(request: Any, **_kwargs: Any) -> None:
        requests.append(request)
        started.set()
        await release.wait()

    import penguin.web.routes as legacy_routes

    monkeypatch.setattr(legacy_routes, "handle_chat_message", blocking_chat)
    first = await routes.session_prompt(
        session_id,
        {"id": "msg_first", "text": "first"},
        core=cast("Any", core),
    )
    await asyncio.wait_for(started.wait(), timeout=1)
    with pytest.raises(routes.OpenCodeV2HTTPError) as raised:
        await routes.session_prompt(
            session_id,
            {"id": "msg_second", "text": "second"},
            core=cast("Any", core),
        )

    assert first["data"]["id"] == "msg_first"
    assert active_sessions_payload(core) == {"data": {session_id: {"type": "running"}}}
    assert raised.value.status_code == 409
    assert raised.value.payload["_tag"] == "SessionBusyError"
    assert [request.client_message_id for request in requests] == ["msg_first"]

    release.set()
    await asyncio.wait_for(routes._prompt_tasks(cast("Any", core))[session_id], 1)
    assert routes._prompt_reservations(cast("Any", core)) == set()


@pytest.mark.asyncio
async def test_fake_provider_prompt_stream_reaches_native_terminal_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Prove the create -> admit -> Penguin chat -> V2 stream seam end to end."""
    core = _Core(tmp_path)
    created = create_session_payload(
        core,
        {
            "agent": "build",
            "model": {"providerID": "openai", "id": "gpt-test"},
        },
        default_directory=str(tmp_path),
    )
    session_id = created["id"]
    admitted = prompt_payload(
        core,
        session_id,
        {"id": "msg_user", "text": "Say hello", "delivery": "steer"},
    )
    assert admitted is not None
    _, request_payload = admitted
    received: list[Any] = []

    async def fake_handle_chat_message(
        request: Any, *, core: Any, http_request: Any
    ) -> None:
        received.append(request)
        source_events = [
            (
                "session.created",
                {
                    "sessionID": session_id,
                    "info": {
                        "id": session_id,
                        "projectID": "penguin",
                        "directory": str(tmp_path),
                        "agent": "build",
                        "providerID": "openai",
                        "modelID": "gpt-test",
                    },
                },
            ),
            ("session.status", {"sessionID": session_id, "status": {"type": "busy"}}),
            (
                "message.updated",
                {
                    "id": "msg_user",
                    "sessionID": session_id,
                    "role": "user",
                    "time": {"created": 1},
                },
            ),
            (
                "message.part.updated",
                {
                    "part": {
                        "id": "part_user",
                        "messageID": "msg_user",
                        "sessionID": session_id,
                        "type": "text",
                        "text": "Say hello",
                    }
                },
            ),
            (
                "message.updated",
                {
                    "id": "msg_assistant",
                    "sessionID": session_id,
                    "role": "assistant",
                    "agent": "build",
                    "providerID": "openai",
                    "modelID": "gpt-test",
                    "time": {"created": 2, "completed": None},
                },
            ),
            (
                "message.part.updated",
                {
                    "part": {
                        "id": "part_assistant",
                        "messageID": "msg_assistant",
                        "sessionID": session_id,
                        "type": "text",
                        "text": "Hello",
                    },
                    "delta": "Hello",
                },
            ),
            (
                "message.updated",
                {
                    "id": "msg_assistant",
                    "sessionID": session_id,
                    "role": "assistant",
                    "agent": "build",
                    "providerID": "openai",
                    "modelID": "gpt-test",
                    "time": {"created": 2, "completed": 3},
                    "finish": "stop",
                },
            ),
            ("session.status", {"sessionID": session_id, "status": {"type": "idle"}}),
        ]
        for event_type, properties in source_events:
            await emit_opencode_event(core, event_type, properties)

    import penguin.web.routes as legacy_routes

    monkeypatch.setattr(legacy_routes, "handle_chat_message", fake_handle_chat_message)
    stream = routes._events(cast("Any", core))
    connected = json.loads((await stream.__anext__()).split("data: ", 1)[1])
    assert connected["type"] == "server.connected"

    try:
        await routes._run_prompt(cast("Any", core), request_payload)
        projected = []
        while not projected or projected[-1]["type"] != "session.execution.succeeded":
            frame = await asyncio.wait_for(stream.__anext__(), timeout=1)
            projected.append(json.loads(frame.split("data: ", 1)[1]))
    finally:
        await stream.aclose()

    assert received[0].client_message_id == "msg_user"
    assert [event["type"] for event in projected] == [
        "session.created",
        "session.input.admitted",
        "session.input.promoted",
        "session.execution.started",
        "session.step.started",
        "session.text.started",
        "session.text.delta",
        "session.text.ended",
        "session.step.ended",
        "session.execution.succeeded",
    ]
    assert projected[7]["data"]["text"] == "Hello"
    assert [
        event["durable"]["seq"] for event in projected if "durable" in event
    ] == list(range(9))


@pytest.mark.asyncio
async def test_background_prompt_failure_synthesizes_native_terminal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    core = _Core(tmp_path)
    created = create_session_payload(core, {}, default_directory=str(tmp_path))
    admitted = prompt_payload(
        core,
        created["id"],
        {"id": "msg_user", "text": "fail early", "delivery": "steer"},
    )
    assert admitted is not None
    _, request_payload = admitted

    async def fail_before_streaming(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("model runtime unavailable")

    import penguin.web.routes as legacy_routes

    monkeypatch.setattr(legacy_routes, "handle_chat_message", fail_before_streaming)
    stream = routes._events(cast("Any", core))
    await stream.__anext__()
    try:
        await routes._run_prompt(cast("Any", core), request_payload)
        projected = []
        while not projected or projected[-1]["type"] != "session.execution.failed":
            frame = await asyncio.wait_for(stream.__anext__(), timeout=1)
            projected.append(json.loads(frame.split("data: ", 1)[1]))
    finally:
        await stream.aclose()

    assert [event["type"] for event in projected] == [
        "session.input.admitted",
        "session.input.promoted",
        "session.execution.started",
        "session.step.started",
        "session.step.failed",
        "session.execution.failed",
    ]
    assert projected[0]["data"]["input"]["data"]["text"] == "fail early"
    assert projected[-1]["data"]["error"] == {
        "type": "APIError",
        "message": "model runtime unavailable",
    }
    assert [event["durable"]["seq"] for event in projected] == list(range(6))


@pytest.mark.asyncio
async def test_interrupt_projects_user_terminal_and_idle_is_noop(
    tmp_path: Path,
) -> None:
    core = _Core(tmp_path)
    created = create_session_payload(core, {}, default_directory=str(tmp_path))
    session_id = created["id"]
    core._opencode_active_requests = {session_id: 1}
    abort_calls: list[str] = []

    async def abort(active_session_id: str) -> bool:
        abort_calls.append(active_session_id)
        await emit_opencode_event(
            core,
            "session.status",
            {"sessionID": active_session_id, "status": {"type": "idle"}},
        )
        return True

    core.abort_session = abort
    stream = routes._events(cast("Any", core))
    await stream.__anext__()
    await emit_opencode_event(
        core,
        "message.updated",
        {
            "id": "msg_interrupt",
            "sessionID": session_id,
            "role": "user",
            "time": {"created": 1},
        },
    )
    await emit_opencode_event(
        core,
        "message.part.updated",
        {
            "part": {
                "id": "part_interrupt",
                "messageID": "msg_interrupt",
                "sessionID": session_id,
                "type": "text",
                "text": "stop",
            }
        },
    )

    try:
        response = await routes.session_interrupt(session_id, core=cast("Any", core))
        projected = []
        while not projected or projected[-1]["type"] != "session.execution.interrupted":
            frame = await asyncio.wait_for(stream.__anext__(), timeout=1)
            projected.append(json.loads(frame.split("data: ", 1)[1]))
    finally:
        await stream.aclose()

    assert response.status_code == 204
    assert abort_calls == [session_id]
    assert [event["type"] for event in projected] == [
        "session.input.admitted",
        "session.input.promoted",
        "session.execution.started",
        "session.execution.interrupted",
    ]
    assert projected[-1]["data"] == {"sessionID": session_id, "reason": "user"}
    assert all(event["type"] != "session.execution.succeeded" for event in projected)

    core._opencode_active_requests = {}
    idle_response = await routes.session_interrupt(session_id, core=cast("Any", core))
    assert idle_response.status_code == 204
    assert abort_calls == [session_id]


@pytest.mark.asyncio
async def test_event_stream_terminates_on_subscriber_overflow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    core = _Core(tmp_path)
    monkeypatch.setattr(routes, "_EVENT_QUEUE_SIZE", 1)
    stream = routes._events(cast("Any", core))
    await stream.__anext__()
    await emit_opencode_event(
        core,
        "message.updated",
        {
            "id": "msg_overflow",
            "sessionID": "session_overflow",
            "role": "user",
            "time": {"created": 1},
        },
    )
    await emit_opencode_event(
        core,
        "message.part.updated",
        {
            "part": {
                "id": "part_overflow",
                "messageID": "msg_overflow",
                "sessionID": "session_overflow",
                "type": "text",
                "text": "too much",
            }
        },
    )

    with pytest.raises(StopAsyncIteration):
        await asyncio.wait_for(stream.__anext__(), timeout=1)
    assert core.event_bus.handlers["opencode_event"] == []


@pytest.mark.asyncio
async def test_event_stream_uses_one_durable_sequence_for_projected_and_fallback(
    tmp_path: Path,
) -> None:
    core = _Core(tmp_path)
    session_id = "session_mixed_sequence"
    stream = routes._events(cast("Any", core))
    await stream.__anext__()
    source_events = [
        (
            "message.updated",
            {
                "id": "msg_sequence_user",
                "sessionID": session_id,
                "role": "user",
                "time": {"created": 1},
            },
        ),
        (
            "message.part.updated",
            {
                "part": {
                    "id": "part_sequence_user",
                    "messageID": "msg_sequence_user",
                    "sessionID": session_id,
                    "type": "text",
                    "text": "sequence me",
                }
            },
        ),
        (
            "message.updated",
            {
                "id": "msg_sequence_assistant",
                "sessionID": session_id,
                "role": "assistant",
                "time": {"created": 2},
            },
        ),
        (
            "message.part.updated",
            {
                "part": {
                    "id": "part_sequence_tool",
                    "messageID": "msg_sequence_assistant",
                    "sessionID": session_id,
                    "type": "tool",
                    "callID": "call_sequence",
                    "tool": "read",
                    "state": {"status": "running", "input": {"path": "README.md"}},
                }
            },
        ),
        (
            "session.updated",
            {
                "sessionID": session_id,
                "info": {
                    "id": session_id,
                    "title": "Mixed sequence",
                    "directory": str(tmp_path),
                    "time": {"created": 1, "updated": 3},
                },
            },
        ),
        (
            "session.deleted",
            {
                "sessionID": session_id,
                "info": {"id": session_id, "directory": str(tmp_path)},
            },
        ),
    ]
    for event_type, properties in source_events:
        await emit_opencode_event(core, event_type, properties)

    expected_types = [
        "session.input.admitted",
        "session.input.promoted",
        "session.execution.started",
        "session.step.started",
        "session.tool.input.started",
        "session.tool.input.ended",
        "session.tool.called",
        "session.renamed",
        "session.deleted",
    ]
    projected = []
    try:
        for _ in expected_types:
            frame = await asyncio.wait_for(stream.__anext__(), timeout=1)
            projected.append(json.loads(frame.split("data: ", 1)[1]))
    finally:
        await stream.aclose()

    assert [event["type"] for event in projected] == expected_types
    assert [event["durable"]["seq"] for event in projected] == list(
        range(len(expected_types))
    )


@pytest.mark.asyncio
async def test_event_stream_handshake_is_first_and_fallback_events_use_data(
    tmp_path: Path,
) -> None:
    core = _Core(tmp_path)
    stream = routes._events(cast("Any", core))
    connected = json.loads((await stream.__anext__()).split("data: ", 1)[1])

    assert connected["id"].startswith(_fixture()["connected"]["id_prefix"])
    assert connected["type"] == "server.connected"
    assert connected["data"] == {}

    await core.event_bus.emit(
        "opencode_event",
        {
            "type": "session.updated",
            "properties": {
                "sessionID": "session_one",
                "info": {
                    "id": "session_one",
                    "title": "Renamed",
                    "directory": str(tmp_path),
                    "time": {"created": 1, "updated": 10},
                },
            },
            "runtime_event": {"id": "evt:source:1", "time": 10, "sequence": 1},
        },
    )
    renamed = json.loads((await stream.__anext__()).split("data: ", 1)[1])
    assert renamed["type"] == "session.renamed"
    assert renamed["data"] == {
        "sessionID": "session_one",
        "title": "Renamed",
    }
    assert renamed["location"] == {"directory": str(tmp_path)}
    await stream.aclose()


def test_event_projector_maps_legacy_session_update_to_v2_rename() -> None:
    projected = event_payload(
        {
            "type": "session.updated",
            "properties": {
                "sessionID": "session_one",
                "info": {
                    "id": "session_one",
                    "title": "New title",
                    "directory": "/tmp",
                    "time": {"created": 1, "updated": 2},
                },
            },
            "runtime_event": {"id": "evt:source:2", "time": 2, "sequence": 2},
        }
    )

    assert projected is not None
    assert projected["type"] == "session.renamed"
    assert projected["data"] == {"sessionID": "session_one", "title": "New title"}
    assert projected["id"].startswith("evt_")


def test_event_projector_preserves_native_session_selection_events() -> None:
    agent = event_payload(
        {
            "type": "session.agent.selected",
            "properties": {"sessionID": "session_one", "agent": "plan"},
        }
    )
    model = event_payload(
        {
            "type": "session.model.selected",
            "properties": {
                "sessionID": "session_one",
                "model": {"providerID": "openai", "id": "gpt-5"},
            },
        }
    )

    assert agent is not None
    assert agent["type"] == "session.agent.selected"
    assert agent["data"] == {"sessionID": "session_one", "agent": "plan"}
    assert model is not None
    assert model["type"] == "session.model.selected"
    assert model["data"] == {
        "sessionID": "session_one",
        "model": {"providerID": "openai", "id": "gpt-5"},
    }
