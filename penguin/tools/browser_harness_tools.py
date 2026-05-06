"""Optional browser-harness backend tools.

This module is intentionally import-safe when browser-harness is not installed.
The actual browser_harness package is imported lazily at execution time so
Penguin's base install and Python 3.9/3.10 users are not penalized.
"""
from __future__ import annotations

import datetime
import importlib
import os
import re
from pathlib import Path
from typing import Any, Dict, Optional


class BrowserHarnessUnavailableError(RuntimeError):
    """Raised when the optional browser-harness backend cannot be used."""


def _slug(value: str) -> str:
    value = value.strip() or "default"
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", value)[:80] or "default"


class BrowserHarnessAdapter:
    """Small adapter around browser-harness helpers and daemon startup."""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}

    @property
    def name(self) -> str:
        configured = self.config.get("name") or self.config.get("bu_name")
        return _slug(str(configured or os.environ.get("BU_NAME", "penguin-default")))

    @property
    def skills_dir(self) -> Optional[str]:
        value = self.config.get("skills_dir")
        if value is None:
            # Backward-compatible read only. New config must use skills_dir.
            value = self.config.get("agent_workspace")
        return str(value) if value else None

    @property
    def screenshot_max_dim(self) -> int:
        return int(self.config.get("screenshot_max_dim", 1800))

    def _base_env(self) -> Dict[str, str]:
        env = {"BU_NAME": self.name}
        if self.skills_dir:
            env["BH_AGENT_WORKSPACE"] = str(Path(self.skills_dir).expanduser())
        if self.config.get("domain_skills"):
            env["BH_DOMAIN_SKILLS"] = "1"
        return env

    def _load_modules(self):
        try:
            admin = importlib.import_module("browser_harness.admin")
            helpers = importlib.import_module("browser_harness.helpers")
        except ModuleNotFoundError as exc:
            raise BrowserHarnessUnavailableError(
                "browser-harness is not installed. Install Penguin with the "
                "browser-harness extra or install browser-harness in this environment."
            ) from exc
        return admin, helpers

    def _ensure_ready(self):
        admin, helpers = self._load_modules()
        env = self._base_env()
        for key, value in env.items():
            os.environ[key] = value
        try:
            admin.ensure_daemon(name=self.name, env=env)
        except Exception as exc:
            raise BrowserHarnessUnavailableError(
                "browser-harness could not connect to Chrome. Start Chrome with "
                "remote debugging enabled and allow remote debugging at "
                "chrome://inspect/#remote-debugging, then retry. "
                f"Original error: {exc}"
            ) from exc
        return helpers

    def open_tab(self, url: str, wait: bool = True, timeout: float = 15.0) -> Dict[str, Any]:
        helpers = self._ensure_ready()
        target_id = helpers.new_tab(url)
        loaded = helpers.wait_for_load(timeout=timeout) if wait else None
        info = helpers.page_info()
        return {
            "result": "Opened browser tab",
            "target_id": target_id,
            "loaded": loaded,
            "page_info": info,
            "backend": "browser-harness",
        }

    def page_info(self) -> Dict[str, Any]:
        helpers = self._ensure_ready()
        return {
            "result": "Browser page info",
            "page_info": helpers.page_info(),
            "backend": "browser-harness",
        }

    def screenshot(
        self,
        full: bool = False,
        max_dim: Optional[int] = None,
        output_dir: Optional[str] = None,
    ) -> Dict[str, Any]:
        helpers = self._ensure_ready()
        directory = Path(
            output_dir
            or self.config.get("screenshot_dir")
            or Path.cwd() / "screenshots"
        )
        directory.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        filepath = directory / f"browser_harness_screenshot_{timestamp}.png"
        resolved_max_dim = self.screenshot_max_dim if max_dim is None else max_dim
        saved_path = helpers.capture_screenshot(
            path=str(filepath),
            full=full,
            max_dim=resolved_max_dim,
        )
        path = Path(saved_path)
        if not path.exists():
            return {"error": f"Screenshot was not saved: {saved_path}"}
        return {
            "result": "Screenshot captured",
            "filepath": str(path),
            "artifact": {
                "type": "image",
                "mime_type": "image/png",
                "path": str(path),
                "image_path": str(path),
                "backend": "browser-harness",
            },
            "timestamp": timestamp,
            "backend": "browser-harness",
            "full": full,
            "max_dim": resolved_max_dim,
            "size_bytes": path.stat().st_size,
        }


class BrowserHarnessOpenTabTool:
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.adapter = BrowserHarnessAdapter(config)

    def execute(self, url: str, wait: bool = True, timeout: float = 15.0) -> Dict[str, Any]:
        return self.adapter.open_tab(url=url, wait=wait, timeout=timeout)


class BrowserHarnessPageInfoTool:
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.adapter = BrowserHarnessAdapter(config)

    def execute(self) -> Dict[str, Any]:
        return self.adapter.page_info()


class BrowserHarnessScreenshotTool:
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.adapter = BrowserHarnessAdapter(config)

    def execute(
        self,
        full: bool = False,
        max_dim: Optional[int] = None,
        output_dir: Optional[str] = None,
    ) -> Dict[str, Any]:
        return self.adapter.screenshot(full=full, max_dim=max_dim, output_dir=output_dir)


__all__ = [
    "BrowserHarnessAdapter",
    "BrowserHarnessOpenTabTool",
    "BrowserHarnessPageInfoTool",
    "BrowserHarnessScreenshotTool",
    "BrowserHarnessUnavailableError",
]
