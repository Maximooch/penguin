"""Tests for Skills web API routes."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

from fastapi import FastAPI
from fastapi.testclient import TestClient

from penguin.skills.manager import SkillManager
from penguin.tools.core.skill_tools import SkillTools
from penguin.web import routes as routes_module


class _EventBus:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    async def emit(self, event_type: str, data: dict[str, Any]) -> None:
        self.events.append((event_type, data))


class _Core:
    def __init__(self, manager: SkillManager) -> None:
        self.conversation_manager = SimpleNamespace(skill_manager=manager)
        self.tool_manager = None
        self.event_bus = _EventBus()


class _CoreWithSkillTools(_Core):
    def __init__(self, manager: SkillManager) -> None:
        super().__init__(manager)
        self.tool_manager = SimpleNamespace(
            skill_tools=SkillTools(
                manager,
                conversation_manager=self.conversation_manager,
            )
        )


def _write_skill(root: Path, name: str = "demo") -> Path:
    skill_dir = root / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\n"
        f"name: {name}\n"
        "description: Demo skill for route tests.\n"
        "allowed-tools:\n"
        "  - read_file\n"
        "---\n"
        "# Demo Skill\n\nUse this for tests.\n",
        encoding="utf-8",
    )
    (skill_dir / "references.md").write_text("reference", encoding="utf-8")
    return skill_dir


def _build_manager(tmp_path: Path) -> SkillManager:
    skills_root = tmp_path / "skills"
    _write_skill(skills_root)
    return SkillManager(
        {
            "skills": {
                "enabled": True,
                "trust_project_skills": True,
                "scan_paths": {
                    "project": [str(skills_root)],
                    "user": [],
                },
            }
        },
        project_root=tmp_path,
    )


def _build_client(tmp_path: Path) -> tuple[TestClient, _Core]:
    core = _Core(_build_manager(tmp_path))
    cast(Any, routes_module.router).core = cast(Any, core)
    app = FastAPI()
    app.include_router(routes_module.router)
    return TestClient(app), core


def _build_client_with_skill_tools(tmp_path: Path) -> tuple[TestClient, _CoreWithSkillTools]:
    core = _CoreWithSkillTools(_build_manager(tmp_path))
    cast(Any, routes_module.router).core = cast(Any, core)
    app = FastAPI()
    app.include_router(routes_module.router)
    return TestClient(app), core


def test_skill_routes_list_show_and_activate(tmp_path: Path) -> None:
    with _build_client(tmp_path)[0] as client:
        catalog = client.get("/api/v1/skills")
        assert catalog.status_code == 200
        data = catalog.json()
        assert data["diagnostic_count"] == 0
        skill_names = {skill["name"] for skill in data["skills"]}
        assert "demo" in skill_names
        demo_entry = next(skill for skill in data["skills"] if skill["name"] == "demo")
        assert demo_entry["active"] is False
        assert data["active"] == []

        detail = client.get("/api/v1/skills/demo")
        assert detail.status_code == 200
        detail_data = detail.json()
        assert detail_data["body"].startswith("# Demo Skill")
        assert detail_data["allowed_tools"] == ["read_file"]
        assert detail_data["active"] is False
        assert "references.md" in detail_data["resources"]

        activated = client.post(
            "/api/v1/skills/demo/activate",
            json={"session_id": "web-session", "load_into_context": False},
        )
        assert activated.status_code == 200
        activated_data = activated.json()
        assert activated_data["status"] == "activated"
        assert activated_data["duplicate"] is False

        active_catalog = client.get("/api/v1/skills", params={"session_id": "web-session"})
        active_data = active_catalog.json()
        active_demo = next(skill for skill in active_data["skills"] if skill["name"] == "demo")
        assert active_data["active"] == ["demo"]
        assert active_demo["active"] is True

        duplicate = client.post(
            "/api/v1/skills/demo/activate",
            json={"session_id": "web-session", "load_into_context": False},
        )
        assert duplicate.status_code == 200
        assert duplicate.json()["status"] == "already_active"


def test_skill_activation_route_handles_sync_skill_tool_adapter(tmp_path: Path) -> None:
    client, _ = _build_client_with_skill_tools(tmp_path)
    with client:
        activate = client.post(
            "/api/v1/skills/demo/activate",
            json={"session_id": "tool-session", "load_into_context": False},
        )
        assert activate.status_code == 200
        data = activate.json()
        assert data["status"] == "activated"
        assert data["skill"]["name"] == "demo"


def test_skill_deactivation_route_toggles_active_state(tmp_path: Path) -> None:
    client, _ = _build_client_with_skill_tools(tmp_path)
    with client:
        activate = client.post(
            "/api/v1/skills/demo/activate",
            json={"session_id": "tool-session", "load_into_context": False},
        )
        assert activate.status_code == 200

        deactivate = client.post(
            "/api/v1/skills/demo/deactivate",
            json={"session_id": "tool-session"},
        )
        assert deactivate.status_code == 200
        data = deactivate.json()
        assert data["status"] == "deactivated"
        assert data["was_active"] is True

        catalog = client.get("/api/v1/skills", params={"session_id": "tool-session"})
        active_demo = next(skill for skill in catalog.json()["skills"] if skill["name"] == "demo")
        assert active_demo["active"] is False


def test_skill_routes_emit_refresh_and_activation_events(tmp_path: Path) -> None:
    client, core = _build_client(tmp_path)
    with client:
        refresh = client.get("/api/v1/skills", params={"refresh": True})
        assert refresh.status_code == 200

        activate = client.post(
            "/api/v1/skills/demo/activate",
            json={"session_id": "s1", "load_into_context": False},
        )
        assert activate.status_code == 200

    emitted_types = [event[1]["type"] for event in core.event_bus.events]
    assert "skills.diagnostics" in emitted_types
    assert "skill.activated" in emitted_types


def test_skill_routes_return_404_for_missing_skill(tmp_path: Path) -> None:
    with _build_client(tmp_path)[0] as client:
        assert client.get("/api/v1/skills/missing").status_code == 404
        assert client.post("/api/v1/skills/missing/activate", json={}).status_code == 404
