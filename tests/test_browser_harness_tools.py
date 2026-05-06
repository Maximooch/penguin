from __future__ import annotations

import sys
import types
from pathlib import Path

from penguin.security.permission_engine import Operation
from penguin.security.tool_permissions import get_tool_operations
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


class _FakeBrowserHarnessModules:
    def __init__(self, monkeypatch):
        self.events = []
        self.admin = types.ModuleType("browser_harness.admin")
        self.helpers = types.ModuleType("browser_harness.helpers")
        self.helpers.page_info = lambda: {
            "url": "https://example.test",
            "title": "Example",
        }
        self.helpers.new_tab = self._new_tab
        self.helpers.wait_for_load = self._wait_for_load
        self.helpers.capture_screenshot = self._capture_screenshot
        self.helpers.click_at_xy = self._click_at_xy
        self.helpers.type_text = self._type_text
        self.helpers.press_key = self._press_key
        self.helpers.fill_input = self._fill_input
        self.helpers.wait_for_element = self._wait_for_element
        self.helpers.wait_for_network_idle = self._wait_for_network_idle
        self.helpers.wait = self._wait
        self.helpers.js = self._js
        self.helpers.list_tabs = self._list_tabs
        self.helpers.current_tab = self._current_tab
        self.helpers.switch_tab = self._switch_tab
        self.admin.ensure_daemon = self._ensure_daemon
        monkeypatch.setitem(sys.modules, "browser_harness.admin", self.admin)
        monkeypatch.setitem(sys.modules, "browser_harness.helpers", self.helpers)

    def _ensure_daemon(self, name=None, env=None, wait=60.0):
        self.events.append(("ensure_daemon", name, dict(env or {}), wait))

    def _new_tab(self, url):
        self.events.append(("new_tab", url))
        return "target-1"

    def _wait_for_load(self, timeout=15.0):
        self.events.append(("wait_for_load", timeout))
        return True

    def _capture_screenshot(self, path=None, full=False, max_dim=None):
        self.events.append(("capture_screenshot", path, full, max_dim))
        output = Path(path)
        output.write_bytes(b"fakepng")
        return str(output)

    def _click_at_xy(self, x, y, button="left", clicks=1):
        self.events.append(("click_at_xy", x, y, button, clicks))

    def _type_text(self, text):
        self.events.append(("type_text", text))

    def _press_key(self, key, modifiers=0):
        self.events.append(("press_key", key, modifiers))

    def _fill_input(self, selector, text, clear_first=True, timeout=0.0):
        self.events.append(("fill_input", selector, text, clear_first, timeout))

    def _wait_for_element(self, selector, timeout=10.0, visible=False):
        self.events.append(("wait_for_element", selector, timeout, visible))
        return True

    def _wait_for_network_idle(self, timeout=10.0, idle_ms=500):
        self.events.append(("wait_for_network_idle", timeout, idle_ms))
        return True

    def _wait(self, seconds=1.0):
        self.events.append(("wait", seconds))

    def _js(self, expression, target_id=None):
        self.events.append(("js", expression, target_id))
        return 42

    def _list_tabs(self, include_chrome=True):
        self.events.append(("list_tabs", include_chrome))
        return [{"targetId": "target-1", "url": "https://example.test"}]

    def _current_tab(self):
        self.events.append(("current_tab",))
        return {"targetId": "target-1", "url": "https://example.test"}

    def _switch_tab(self, target_id):
        self.events.append(("switch_tab", target_id))
        return "session-1"


def test_browser_harness_phase_1_tools_register() -> None:
    manager = ToolManager(config={}, log_error_func=_dummy_log_error, fast_startup=True)
    names = {schema["name"] for schema in manager.tools}

    expected = {
        "browser_click",
        "browser_type",
        "browser_key",
        "browser_fill",
        "browser_wait",
        "browser_js",
        "browser_list_tabs",
        "browser_switch_tab",
    }

    assert expected.issubset(names)
    assert expected.issubset(manager._tool_registry)


def test_browser_harness_phase_1_dispatch(monkeypatch) -> None:
    fake = _FakeBrowserHarnessModules(monkeypatch)
    manager = ToolManager(config={}, log_error_func=_dummy_log_error, fast_startup=True)

    click_result = manager.execute_tool("browser_click", {"x": 10, "y": 20})
    assert click_result["result"] == "Clicked browser coordinates"
    assert manager.execute_tool("browser_type", {"text": "hello"})["text_length"] == 5
    assert manager.execute_tool("browser_key", {"key": "Enter"})["key"] == "Enter"
    assert manager.execute_tool(
        "browser_fill",
        {"selector": "#email", "text": "a@b.test", "timeout": 1.5},
    )["selector"] == "#email"
    assert manager.execute_tool(
        "browser_wait",
        {"mode": "element", "selector": "#done", "visible": True},
    )["ok"] is True
    assert manager.execute_tool("browser_js", {"expression": "1 + 1"})["value"] == 42
    tabs_result = manager.execute_tool("browser_list_tabs", {})
    assert tabs_result["tabs"][0]["targetId"] == "target-1"
    switch_result = manager.execute_tool("browser_switch_tab", {"target_id": "target-1"})
    assert switch_result["session_id"] == "session-1"

    event_names = [event[0] for event in fake.events]
    assert "click_at_xy" in event_names
    assert "type_text" in event_names
    assert "press_key" in event_names
    assert "fill_input" in event_names
    assert "wait_for_element" in event_names
    assert "js" in event_names
    assert "list_tabs" in event_names
    assert "switch_tab" in event_names


def test_browser_harness_permission_operations() -> None:
    assert get_tool_operations("browser_click") == [Operation.NETWORK_POST]
    assert get_tool_operations("browser_js") == [Operation.NETWORK_POST]
    assert get_tool_operations("browser_wait") == [Operation.NETWORK_FETCH]
    assert get_tool_operations("browser_list_tabs") == [Operation.NETWORK_FETCH]
