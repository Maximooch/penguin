from __future__ import annotations

import sys
import types
from pathlib import Path

from penguin.tools.browser_harness_tools import BrowserHarnessAdapter
from penguin.tools.tool_manager import ToolManager


def _dummy_log_error(exc: Exception, context: str = "") -> None:
    del exc, context


def test_browser_harness_config_uses_skills_dir_name() -> None:
    adapter = BrowserHarnessAdapter(
        {
            "name": "session:one",
            "skills_dir": "context/browser_harness",
            "domain_skills": True,
        }
    )

    env = adapter._base_env()

    assert env["BU_NAME"] == "session-one"
    assert env["BH_AGENT_WORKSPACE"].endswith("context/browser_harness")
    assert env["BH_DOMAIN_SKILLS"] == "1"


def test_browser_harness_tools_register_without_optional_dependency() -> None:
    manager = ToolManager(config={}, log_error_func=_dummy_log_error, fast_startup=True)
    names = {schema["name"] for schema in manager.tools}

    assert "browser_open_tab" in names
    assert "browser_page_info" in names
    assert "browser_harness_screenshot" in names
    assert "browser_open_tab" in manager._tool_registry


def test_browser_harness_missing_dependency_returns_actionable_error(monkeypatch) -> None:
    manager = ToolManager(config={}, log_error_func=_dummy_log_error, fast_startup=True)

    real_import = __import__

    def fake_import(name, *args, **kwargs):
        if name.startswith("browser_harness"):
            raise ModuleNotFoundError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("importlib.import_module", lambda name: fake_import(name))

    result = manager.execute_tool("browser_page_info", {})

    assert "error" in result
    assert "browser-harness is not installed" in result["error"]


def test_browser_harness_screenshot_returns_multimodal_artifact(
    monkeypatch, tmp_path: Path
) -> None:
    fake_admin = types.ModuleType("browser_harness.admin")
    fake_helpers = types.ModuleType("browser_harness.helpers")

    def ensure_daemon(name=None, env=None, wait=60.0):
        del name, env, wait

    def capture_screenshot(path=None, full=False, max_dim=None):
        del full, max_dim
        output = Path(path)
        output.write_bytes(b"fakepng")
        return str(output)

    fake_admin.ensure_daemon = ensure_daemon
    fake_helpers.capture_screenshot = capture_screenshot
    monkeypatch.setitem(sys.modules, "browser_harness.admin", fake_admin)
    monkeypatch.setitem(sys.modules, "browser_harness.helpers", fake_helpers)

    manager = ToolManager(
        config={"browser": {"harness": {"skills_dir": str(tmp_path / "skills")}}},
        log_error_func=_dummy_log_error,
        fast_startup=True,
    )

    result = manager.execute_tool(
        "browser_harness_screenshot",
        {"output_dir": str(tmp_path), "max_dim": 1200},
    )

    assert result["result"] == "Screenshot captured"
    assert Path(result["filepath"]).exists()
    assert result["artifact"]["type"] == "image"
    assert result["artifact"]["image_path"] == result["filepath"]
