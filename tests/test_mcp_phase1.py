from __future__ import annotations

import json

from penguin.integrations.mcp.config import load_mcp_server_configs
from penguin.integrations.mcp.manager import MCPToolDefinition
from penguin.integrations.mcp.names import (
    is_mcp_tool_name,
    make_tool_name,
    sanitize_part,
)
from penguin.tools.providers.mcp import MCPToolProvider
from penguin.tools.tool_manager import ToolManager


class FakeManager:
    def __init__(self) -> None:
        self.called_with = None

    def list_tools_sync(self) -> list[MCPToolDefinition]:
        return [
            MCPToolDefinition(
                public_name="mcp__local_fs__read_file",
                server_name="local-fs",
                raw_name="read-file",
                description="Read a file through MCP",
                input_schema={
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
            )
        ]

    def call_tool_sync(self, public_name: str, arguments: dict) -> dict:
        self.called_with = (public_name, arguments)
        return {"public_name": public_name, "arguments": arguments}

    def refresh_sync(self):
        return self.list_tools_sync()

    def reconnect_sync(self, server_name=None) -> dict:
        return {
            "available": True,
            "discovered": True,
            "servers": {"local-fs": {"status": "connected"}},
        }

    def close_sync(self) -> dict:
        return {
            "available": True,
            "discovered": True,
            "servers": {"local-fs": {"status": "disconnected"}},
        }

    def status(self) -> dict:
        return {
            "available": True,
            "discovered": True,
            "server_count": 1,
            "tool_count": 1,
            "servers": {},
        }


def test_mcp_config_parses_mapping_servers_and_env(monkeypatch) -> None:
    monkeypatch.setenv("MCP_TOKEN", "secret-value")
    configs = load_mcp_server_configs(
        {
            "mcp": {
                "enabled": True,
                "servers": {
                    "filesystem": {
                        "command": "uvx",
                        "args": ["mcp-server-filesystem"],
                        "env": {"TOKEN": "$MCP_TOKEN"},
                        "disabled_tools": ["write_file"],
                    }
                },
            }
        }
    )

    assert len(configs) == 1
    server = configs[0]
    assert server.name == "filesystem"
    assert server.command == "uvx"
    assert server.args == ["mcp-server-filesystem"]
    assert server.env == {"TOKEN": "secret-value"}
    assert server.allows_tool("read_file") is True
    assert server.allows_tool("write_file") is False


def test_mcp_config_is_disabled_by_default() -> None:
    assert load_mcp_server_configs({}) == []
    assert load_mcp_server_configs({"mcp": {"enabled": False}}) == []


def test_mcp_tool_name_sanitization_and_collision() -> None:
    first = make_tool_name("Local FS", "read-file")
    second = make_tool_name("Local FS", "read-file", existing=[first])

    assert first == "mcp__local_fs__read_file"
    assert second == "mcp__local_fs__read_file_2"
    assert sanitize_part("../Bad Name!!") == "bad_name"
    assert is_mcp_tool_name(first) is True
    assert is_mcp_tool_name("read_file") is False


def test_mcp_provider_exposes_schemas_and_dispatches() -> None:
    provider = MCPToolProvider(
        {
            "mcp": {
                "enabled": True,
                "servers": {"local-fs": {"command": "fake"}},
            }
        }
    )
    fake_manager = FakeManager()
    provider._manager = fake_manager

    schemas = provider.get_tool_schemas()
    assert schemas == [
        {
            "name": "mcp__local_fs__read_file",
            "description": "Read a file through MCP",
            "input_schema": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
            "metadata": {
                "provider": "mcp",
                "mcp_server": "local-fs",
                "mcp_tool": "read-file",
            },
        }
    ]

    payload = json.loads(
        provider.execute_tool("mcp__local_fs__read_file", {"path": "README.md"})
    )
    assert payload["status"] == "ok"
    assert payload["result"] == {
        "public_name": "mcp__local_fs__read_file",
        "arguments": {"path": "README.md"},
    }
    assert fake_manager.called_with == (
        "mcp__local_fs__read_file",
        {"path": "README.md"},
    )


def test_tool_manager_exposes_and_dispatches_mcp_tools() -> None:
    manager = ToolManager(
        {
            "mcp": {
                "enabled": True,
                "servers": {"local-fs": {"command": "fake"}},
            }
        },
        lambda *_args, **_kwargs: None,
        fast_startup=True,
    )
    fake_manager = FakeManager()
    manager._mcp_provider._manager = fake_manager

    tool_names = {tool["name"] for tool in manager.get_tools()}
    assert "mcp__local_fs__read_file" in tool_names

    payload = json.loads(
        manager.execute_tool("mcp__local_fs__read_file", {"path": "README.md"})
    )
    assert payload["status"] == "ok"
    assert fake_manager.called_with == (
        "mcp__local_fs__read_file",
        {"path": "README.md"},
    )


def test_mcp_provider_gracefully_noops_when_disabled() -> None:
    provider = MCPToolProvider({})

    assert provider.get_tool_schemas() == []
    payload = json.loads(provider.execute_tool("mcp__missing__tool", {}))
    assert payload["error"] == "mcp_disabled"



def test_mcp_config_accepts_claude_style_mcp_servers() -> None:
    configs = load_mcp_server_configs(
        {
            "mcpServers": {
                "everything": {
                    "command": "npx",
                    "args": ["-y", "@modelcontextprotocol/server-everything"],
                    "startupTimeoutSec": 30,
                    "toolTimeoutSec": 120,
                }
            }
        }
    )

    assert len(configs) == 1
    server = configs[0]
    assert server.name == "everything"
    assert server.command == "npx"
    assert server.startup_timeout_sec == 30
    assert server.tool_timeout_sec == 120


def test_mcp_provider_status_refresh_reconnect_and_close() -> None:
    provider = MCPToolProvider(
        {
            "mcp": {
                "enabled": True,
                "servers": {"local-fs": {"command": "fake"}},
            }
        }
    )
    fake_manager = FakeManager()
    provider._manager = fake_manager

    assert provider.status()["initialized"] is True
    assert provider.refresh()[0]["name"] == "mcp__local_fs__read_file"
    assert (
        provider.reconnect("local-fs")["servers"]["local-fs"]["status"]
        == "connected"
    )
    assert provider.close()["servers"]["local-fs"]["status"] == "disconnected"


def test_tool_manager_mcp_diagnostic_facade() -> None:
    manager = ToolManager(
        {
            "mcp": {
                "enabled": True,
                "servers": {"local-fs": {"command": "fake"}},
            }
        },
        lambda *_args, **_kwargs: None,
        fast_startup=True,
    )
    fake_manager = FakeManager()
    manager._mcp_provider._manager = fake_manager

    assert manager.get_mcp_status()["initialized"] is True
    assert manager.refresh_mcp_tools()[0]["name"] == "mcp__local_fs__read_file"
    assert (
        manager.reconnect_mcp("local-fs")["servers"]["local-fs"]["status"]
        == "connected"
    )
    assert manager.close_mcp()["servers"]["local-fs"]["status"] == "disconnected"

def test_penguin_mcp_server_exposes_safe_tools_only() -> None:
    from penguin.integrations.mcp.server import build_penguin_mcp_server

    manager = ToolManager({}, lambda *_args, **_kwargs: None, fast_startup=True)
    server = build_penguin_mcp_server(manager)
    exposed = {tool["name"] for tool in server.list_exposed_tools()}

    assert {"read_file", "list_files", "find_file", "grep_search", "analyze_project"} <= exposed
    assert "execute" not in exposed
    assert "write_file" not in exposed
    assert all(not name.startswith("mcp__") for name in exposed)


def test_penguin_mcp_server_routes_calls_through_tool_manager() -> None:
    from penguin.integrations.mcp.server import build_penguin_mcp_server

    class FakeToolManager:
        def __init__(self) -> None:
            self.called_with = None

        def get_tools(self):
            return [
                {
                    "name": "read_file",
                    "description": "Read a file",
                    "input_schema": {
                        "type": "object",
                        "properties": {"path": {"type": "string"}},
                        "required": ["path"],
                    },
                },
                {
                    "name": "execute",
                    "description": "Run a command",
                    "input_schema": {"type": "object", "properties": {}},
                },
            ]

        def execute_tool(self, tool_name, arguments):
            self.called_with = (tool_name, arguments)
            return {"ok": True, "tool": tool_name, "arguments": arguments}

    fake = FakeToolManager()
    server = build_penguin_mcp_server(fake)
    result = json.loads(server.call_tool("read_file", {"path": "README.md"}))

    assert result["ok"] is True
    assert fake.called_with == ("read_file", {"path": "README.md"})
    assert json.loads(server.call_tool("execute", {}))["error"] == "tool_not_exposed"


def test_penguin_mcp_server_dynamic_handler_signature() -> None:
    import inspect
    from penguin.integrations.mcp.server import build_penguin_mcp_server

    class FakeToolManager:
        def get_tools(self):
            return [
                {
                    "name": "find_file",
                    "description": "Find a file",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "filename": {"type": "string"},
                            "search_path": {"type": "string"},
                        },
                        "required": ["filename"],
                    },
                }
            ]

        def execute_tool(self, tool_name, arguments):
            return arguments

    server = build_penguin_mcp_server(FakeToolManager(), allow_tools=["find_file"])
    handler = server._build_tool_handler(server.list_exposed_tools()[0])
    signature = inspect.signature(handler)

    assert "filename" in signature.parameters
    assert signature.parameters["filename"].default is inspect.Parameter.empty
    assert signature.parameters["search_path"].default is None


def test_penguin_mcp_server_exposes_pm_tools_with_core(tmp_path) -> None:
    from penguin.integrations.mcp.server import build_penguin_mcp_server
    from penguin.project.manager import ProjectManager

    class FakeCore:
        def __init__(self) -> None:
            self.project_manager = ProjectManager(tmp_path)

    class FakeToolManager:
        def __init__(self, core) -> None:
            self._core = core

        def get_tools(self):
            return []

        def execute_tool(self, tool_name, arguments):
            raise AssertionError("PM tools should not route through ToolManager")

    core = FakeCore()
    server = build_penguin_mcp_server(FakeToolManager(core), core=core)
    exposed = {tool["name"] for tool in server.list_exposed_tools()}

    assert {
        "penguin_pm_list_projects",
        "penguin_pm_create_project",
        "penguin_pm_get_project",
        "penguin_pm_list_tasks",
        "penguin_pm_create_task",
        "penguin_pm_get_task",
    } <= exposed


def test_penguin_mcp_pm_project_and_task_lifecycle(tmp_path) -> None:
    from penguin.integrations.mcp.server import build_penguin_mcp_server
    from penguin.project.manager import ProjectManager

    class FakeCore:
        def __init__(self) -> None:
            self.project_manager = ProjectManager(tmp_path)

    class FakeToolManager:
        def __init__(self, core) -> None:
            self._core = core

        def get_tools(self):
            return []

        def execute_tool(self, tool_name, arguments):
            raise AssertionError("PM tools should not route through ToolManager")

    core = FakeCore()
    server = build_penguin_mcp_server(FakeToolManager(core), core=core)

    project_payload = json.loads(
        server.call_tool(
            "penguin_pm_create_project",
            {
                "name": "MCP Slice 1",
                "description": "PM control plane",
                "tags": ["mcp"],
                "metadata": {"source": "test"},
            },
        )
    )
    project = project_payload["project"]
    assert project["name"] == "MCP Slice 1"
    assert project["metadata"] == {"source": "test"}

    task_payload = json.loads(
        server.call_tool(
            "penguin_pm_create_task",
            {
                "project_id": project["id"],
                "title": "Implement PM tools",
                "description": "Expose PM over MCP",
                "acceptance_criteria": ["tools/list includes PM tools"],
                "definition_of_done": "verified",
                "metadata": {"risk": "low"},
            },
        )
    )
    task = task_payload["task"]
    assert task["project_id"] == project["id"]
    assert task["title"] == "Implement PM tools"
    assert task["acceptance_criteria"] == ["tools/list includes PM tools"]
    assert task["definition_of_done"] == "verified"
    assert task["metadata"] == {"risk": "low"}

    list_payload = json.loads(
        server.call_tool("penguin_pm_list_tasks", {"project_id": project["id"]})
    )
    assert [item["id"] for item in list_payload["tasks"]] == [task["id"]]

    fetched = json.loads(
        server.call_tool("penguin_pm_get_project", {"project_id": project["id"]})
    )
    assert fetched["project"]["tasks"][0]["id"] == task["id"]


def test_penguin_mcp_server_exposes_blueprint_tools_with_core(tmp_path) -> None:
    from penguin.integrations.mcp.server import build_penguin_mcp_server
    from penguin.project.manager import ProjectManager

    class FakeCore:
        def __init__(self) -> None:
            self.project_manager = ProjectManager(tmp_path)

    class FakeToolManager:
        def __init__(self, core) -> None:
            self._core = core

        def get_tools(self):
            return []

        def execute_tool(self, tool_name, arguments):
            raise AssertionError("Blueprint tools should not route through ToolManager")

    core = FakeCore()
    server = build_penguin_mcp_server(FakeToolManager(core), core=core)
    exposed = {tool["name"] for tool in server.list_exposed_tools()}

    assert {
        "penguin_blueprint_lint",
        "penguin_blueprint_graph",
        "penguin_blueprint_status",
    } <= exposed


def test_penguin_mcp_blueprint_lint_and_graph_from_yaml(tmp_path) -> None:
    from penguin.integrations.mcp.server import build_penguin_mcp_server
    from penguin.project.manager import ProjectManager

    class FakeCore:
        def __init__(self) -> None:
            self.project_manager = ProjectManager(tmp_path)

    class FakeToolManager:
        def __init__(self, core) -> None:
            self._core = core

        def get_tools(self):
            return []

        def execute_tool(self, tool_name, arguments):
            raise AssertionError("Blueprint tools should not route through ToolManager")

    blueprint = """
title: MCP Blueprint
project_key: MCP
items:
  - id: BASE
    title: Base task
    description: Base task
    acceptance_criteria:
      - base works
  - id: CHILD
    title: Child task
    description: Child task
    depends_on:
      - BASE
""".strip()
    core = FakeCore()
    server = build_penguin_mcp_server(FakeToolManager(core), core=core)

    lint_payload = json.loads(
        server.call_tool(
            "penguin_blueprint_lint",
            {"content": blueprint, "format": "yaml", "source": "inline.yaml"},
        )
    )
    assert lint_payload["blueprint"]["title"] == "MCP Blueprint"
    assert lint_payload["diagnostics"]["has_errors"] is False

    graph_payload = json.loads(
        server.call_tool(
            "penguin_blueprint_graph",
            {
                "content": blueprint,
                "format": "yaml",
                "source": "inline.yaml",
                "output_format": "dot",
            },
        )
    )
    assert {node["id"] for node in graph_payload["graph"]["nodes"]} == {
        "BASE",
        "CHILD",
    }
    assert graph_payload["graph"]["edges"] == [
        {"from": "BASE", "to": "CHILD", "policy": "completion_required", "artifact_key": None}
    ]
    assert "digraph BlueprintDAG" in graph_payload["dot"]


def test_penguin_mcp_blueprint_status_reports_project_dag(tmp_path) -> None:
    from penguin.integrations.mcp.server import build_penguin_mcp_server
    from penguin.project.manager import ProjectManager
    from penguin.project.blueprint_parser import BlueprintParser

    class FakeCore:
        def __init__(self) -> None:
            self.project_manager = ProjectManager(tmp_path)

    class FakeToolManager:
        def __init__(self, core) -> None:
            self._core = core

        def get_tools(self):
            return []

        def execute_tool(self, tool_name, arguments):
            raise AssertionError("Blueprint tools should not route through ToolManager")

    blueprint = BlueprintParser().parse_yaml(
        """
title: Status Blueprint
project_key: STAT
items:
  - id: ROOT
    title: Root
    description: Root
    acceptance_criteria:
      - root works
  - id: LEAF
    title: Leaf
    description: Leaf
    depends_on:
      - ROOT
""".strip(),
        source="status.yaml",
    )
    core = FakeCore()
    sync_result = core.project_manager.sync_blueprint(blueprint)
    server = build_penguin_mcp_server(FakeToolManager(core), core=core)

    payload = json.loads(
        server.call_tool(
            "penguin_blueprint_status",
            {"project_id": sync_result["project_id"], "include_tasks": True},
        )
    )

    assert payload["stats"]["total_tasks"] == 2
    assert payload["stats"]["total_edges"] == 1
    assert payload["blueprint_task_count"] == 2
    assert {task["blueprint_id"] for task in payload["tasks"]} == {"ROOT", "LEAF"}


def test_penguin_mcp_blueprint_sync_dry_run_defaults_to_safe_no_mutation(tmp_path) -> None:
    from penguin.integrations.mcp.server import build_penguin_mcp_server
    from penguin.project.manager import ProjectManager

    class FakeCore:
        def __init__(self) -> None:
            self.project_manager = ProjectManager(tmp_path)

    class FakeToolManager:
        def __init__(self, core) -> None:
            self._core = core

        def get_tools(self):
            return []

        def execute_tool(self, tool_name, arguments):
            raise AssertionError("Blueprint tools should not route through ToolManager")

    core = FakeCore()
    server = build_penguin_mcp_server(FakeToolManager(core), core=core)
    project_payload = json.loads(
        server.call_tool("penguin_pm_create_project", {"name": "Sync Dry Run"})
    )
    project_id = project_payload["project"]["id"]
    blueprint = """
title: Dry Blueprint
project_key: DRY
items:
  - id: ROOT
    title: Root
    description: Root
    acceptance_criteria:
      - root works
  - id: LEAF
    title: Leaf
    description: Leaf
    depends_on:
      - ROOT
""".strip()

    payload = json.loads(
        server.call_tool(
            "penguin_blueprint_sync",
            {"project_id": project_id, "content": blueprint, "format": "yaml"},
        )
    )

    assert payload["status"] == "dry_run"
    assert payload["sync"]["created"] == ["ROOT", "LEAF"]
    assert payload["sync"]["updated"] == []
    assert payload["sync"]["total_items"] == 2
    assert core.project_manager.list_tasks(project_id=project_id) == []


def test_penguin_mcp_blueprint_sync_mutates_when_dry_run_false(tmp_path) -> None:
    from penguin.integrations.mcp.server import build_penguin_mcp_server
    from penguin.project.manager import ProjectManager

    class FakeCore:
        def __init__(self) -> None:
            self.project_manager = ProjectManager(tmp_path)

    class FakeToolManager:
        def __init__(self, core) -> None:
            self._core = core

        def get_tools(self):
            return []

        def execute_tool(self, tool_name, arguments):
            raise AssertionError("Blueprint tools should not route through ToolManager")

    core = FakeCore()
    server = build_penguin_mcp_server(FakeToolManager(core), core=core)
    blueprint = """
title: Apply Blueprint
project_key: APPLY
items:
  - id: ROOT
    title: Root
    description: Root
    acceptance_criteria:
      - root works
  - id: LEAF
    title: Leaf
    description: Leaf
    depends_on:
      - ROOT
""".strip()

    payload = json.loads(
        server.call_tool(
            "penguin_blueprint_sync",
            {
                "content": blueprint,
                "format": "yaml",
                "create_project": True,
                "dry_run": False,
                "include_tasks": True,
            },
        )
    )

    assert payload["status"] == "synced"
    assert payload["sync"]["created"] == ["ROOT", "LEAF"]
    assert payload["sync"]["updated"] == []
    assert len(payload["tasks"]) == 2
    assert {task["blueprint_id"] for task in payload["tasks"]} == {"ROOT", "LEAF"}


def test_penguin_mcp_blueprint_sync_rejects_errors(tmp_path) -> None:
    from penguin.integrations.mcp.server import build_penguin_mcp_server
    from penguin.project.manager import ProjectManager

    class FakeCore:
        def __init__(self) -> None:
            self.project_manager = ProjectManager(tmp_path)

    class FakeToolManager:
        def __init__(self, core) -> None:
            self._core = core

        def get_tools(self):
            return []

        def execute_tool(self, tool_name, arguments):
            raise AssertionError("Blueprint tools should not route through ToolManager")

    core = FakeCore()
    server = build_penguin_mcp_server(FakeToolManager(core), core=core)
    blueprint = """
title: Broken Blueprint
project_key: BROKEN
items:
  - id: CHILD
    title: Child
    description: Child
    depends_on:
      - MISSING
""".strip()

    payload = json.loads(
        server.call_tool(
            "penguin_blueprint_sync",
            {
                "content": blueprint,
                "format": "yaml",
                "create_project": True,
                "dry_run": False,
            },
        )
    )

    assert payload["status"] == "rejected"
    assert payload["reason"] == "lint_errors"
    assert payload["diagnostics"]["has_errors"] is True
    assert core.project_manager.list_projects() == []


def test_penguin_mcp_runmode_tools_are_opt_in(tmp_path) -> None:
    from penguin.integrations.mcp.server import build_penguin_mcp_server
    from penguin.project.manager import ProjectManager

    class FakeCore:
        def __init__(self) -> None:
            self.project_manager = ProjectManager(tmp_path)
            self.engine = object()
            self._runmode_active = False
            self._continuous_mode = False
            self.current_runmode_status_summary = None

        async def start_run_mode(self, *args, **kwargs):
            raise AssertionError("Slice 3A must not start RunMode")

    class FakeToolManager:
        def __init__(self, core) -> None:
            self._core = core

        def get_tools(self):
            return []

        def execute_tool(self, tool_name, arguments):
            raise AssertionError("RunMode tools should not route through ToolManager")

    core = FakeCore()
    default_server = build_penguin_mcp_server(FakeToolManager(core), core=core)
    default_exposed = {tool["name"] for tool in default_server.list_exposed_tools()}
    assert "penguin_runmode_capabilities" not in default_exposed

    runtime_server = build_penguin_mcp_server(
        FakeToolManager(core),
        core=core,
        expose_runtime_tools=True,
    )
    exposed = {tool["name"] for tool in runtime_server.list_exposed_tools()}
    assert {
        "penguin_runmode_capabilities",
        "penguin_runmode_list_jobs",
        "penguin_runmode_get_job",
    } <= exposed

    capabilities = json.loads(
        runtime_server.call_tool("penguin_runmode_capabilities", {})
    )
    assert capabilities["runtime_tools_enabled"] is True
    assert capabilities["start_supported"] is False
    assert capabilities["cancel_supported"] is False
    assert capabilities["core"]["has_project_manager"] is True
    assert capabilities["core"]["has_engine"] is True


def test_penguin_mcp_runmode_job_read_tools(tmp_path) -> None:
    from penguin.integrations.mcp.server import build_penguin_mcp_server
    from penguin.project.manager import ProjectManager

    class FakeCore:
        def __init__(self) -> None:
            self.project_manager = ProjectManager(tmp_path)
            self.engine = object()

        async def start_run_mode(self, *args, **kwargs):
            raise AssertionError("Slice 3A must not start RunMode")

    class FakeToolManager:
        def __init__(self, core) -> None:
            self._core = core

        def get_tools(self):
            return []

        def execute_tool(self, tool_name, arguments):
            raise AssertionError("RunMode tools should not route through ToolManager")

    core = FakeCore()
    server = build_penguin_mcp_server(
        FakeToolManager(core),
        core=core,
        expose_runtime_tools=True,
    )

    jobs = json.loads(server.call_tool("penguin_runmode_list_jobs", {}))
    assert jobs["jobs"] == []
    assert jobs["registry"]["supports_start"] is False

    missing = json.loads(
        server.call_tool("penguin_runmode_get_job", {"job_id": "missing"})
    )
    assert missing["error"] == "job_not_found"

