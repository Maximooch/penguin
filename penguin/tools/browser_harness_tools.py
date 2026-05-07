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
import socket
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from penguin.system.execution_context import get_current_execution_context_dict


class BrowserHarnessUnavailableError(RuntimeError):
    """Raised when the optional browser-harness backend cannot be used."""


def _slug(value: str) -> str:
    value = value.strip() or "default"
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", value)[:80] or "default"


class BrowserHarnessAdapter:
    """Small adapter around browser-harness helpers and daemon startup."""

    def __init__(
        self,
        config: Optional[Dict[str, Any]] = None,
        execution_context: Optional[Dict[str, Any]] = None,
    ):
        self.config = config or {}
        self.execution_context = execution_context or {}

    @property
    def session_id(self) -> Optional[str]:
        value = self.config.get("session_id") or self.execution_context.get(
            "session_id"
        )
        return str(value) if value else None

    @property
    def agent_id(self) -> Optional[str]:
        value = self.config.get("agent_id") or self.execution_context.get(
            "agent_id"
        )
        return str(value) if value else None

    @property
    def name(self) -> str:
        configured = self.config.get("name") or self.config.get("bu_name")
        if configured:
            return _slug(str(configured))
        if self.session_id or self.agent_id:
            identity = ":".join(
                part for part in ["penguin", self.session_id, self.agent_id] if part
            )
            return _slug(identity)
        return _slug(os.environ.get("BU_NAME", "penguin-default"))

    @property
    def started_by_penguin(self) -> bool:
        return bool(self.config.get("started_by_penguin", True))

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

    @property
    def domain_skills_enabled(self) -> bool:
        return bool(self.config.get("domain_skills"))

    def _base_env(self) -> Dict[str, str]:
        env = {"BU_NAME": self.name}
        env["PENGUIN_BROWSER_OWNED"] = "1" if self.started_by_penguin else "0"
        if self.session_id:
            env["PENGUIN_SESSION_ID"] = self.session_id
        if self.agent_id:
            env["PENGUIN_AGENT_ID"] = self.agent_id
        if self.skills_dir:
            env["BH_AGENT_WORKSPACE"] = str(Path(self.skills_dir).expanduser())
        if self.domain_skills_enabled:
            env["BH_DOMAIN_SKILLS"] = "1"
        return env

    def _domain_skill_roots(self) -> List[Path]:
        roots: List[Path] = []
        configured = self.config.get("domain_skill_roots") or []
        if isinstance(configured, (str, Path)):
            configured = [configured]
        for root in configured:
            roots.append(Path(str(root)).expanduser())
        if self.skills_dir:
            roots.append(Path(self.skills_dir).expanduser() / "domain-skills")
        bundled_root = (
            Path(__file__).resolve().parents[1]
            / "bundled_skills"
            / "browser"
            / "domain-skills"
        )
        roots.append(bundled_root)
        deduped: List[Path] = []
        seen = set()
        for root in roots:
            key = str(root)
            if key not in seen:
                deduped.append(root)
                seen.add(key)
        return deduped

    @staticmethod
    def _domain_candidate_slugs(url: str) -> List[str]:
        parsed = urlparse(url if "://" in url else f"https://{url}")
        hostname = (parsed.hostname or "").lower().strip(".")
        if hostname.startswith("www."):
            hostname = hostname[4:]
        if not hostname:
            return []

        labels = [label for label in hostname.split(".") if label]
        candidates = [hostname.replace(".", "-")]
        if len(labels) >= 2:
            candidates.append(labels[-2])
        if len(labels) >= 3:
            candidates.append("-".join(labels[-3:-1]))
        candidates.extend(labels[:-1])

        deduped: List[str] = []
        for candidate in candidates:
            slug = _slug(candidate.lower())
            if slug and slug not in deduped:
                deduped.append(slug)
        return deduped

    def domain_skill_matches(self, url: str) -> Dict[str, Any]:
        parsed = urlparse(url if "://" in url else f"https://{url}")
        hostname = (parsed.hostname or "").lower().strip(".")
        if hostname.startswith("www."):
            hostname = hostname[4:]
        payload: Dict[str, Any] = {
            "enabled": self.domain_skills_enabled,
            "hostname": hostname,
            "matches": [],
        }
        if not self.domain_skills_enabled or not hostname:
            return payload

        candidate_slugs = self._domain_candidate_slugs(url)
        roots = self._domain_skill_roots()
        payload["candidate_slugs"] = candidate_slugs
        payload["searched_roots"] = [str(root) for root in roots]

        matches = []
        for root in roots:
            if not root.exists():
                continue
            for slug in candidate_slugs:
                directory = root / slug
                if not directory.is_dir():
                    continue
                files = sorted(str(path) for path in directory.glob("*.md"))
                matches.append(
                    {
                        "slug": slug,
                        "path": str(directory),
                        "files": files,
                    }
                )
        payload["matches"] = matches
        return payload

    def _load_modules(self, env: Optional[Dict[str, str]] = None):
        for key, value in (env or {}).items():
            os.environ[key] = value
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
        env = self._base_env()
        admin, helpers = self._load_modules(env)
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

    def identity(self) -> Dict[str, Any]:
        return {
            "backend": "browser-harness",
            "bu_name": self.name,
            "session_id": self.session_id,
            "agent_id": self.agent_id,
            "skills_dir": self.skills_dir,
            "domain_skills_enabled": self.domain_skills_enabled,
            "started_by_penguin": self.started_by_penguin,
            "env": self._base_env(),
        }

    def status(self, include_page: bool = True) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "result": "Browser harness status",
            "identity": self.identity(),
            "python": {"executable": os.sys.executable},
            "host": {"hostname": socket.gethostname()},
        }
        try:
            helpers = self._ensure_ready()
        except BrowserHarnessUnavailableError as exc:
            payload["connected"] = False
            payload["error"] = str(exc)
            return payload

        payload["connected"] = True
        if include_page:
            info = helpers.page_info()
            payload["page_info"] = info
            if isinstance(info, dict):
                payload["domain_skills"] = self.domain_skill_matches(
                    info.get("url", "")
                )
        return payload

    def open_tab(
        self,
        url: str,
        wait: bool = True,
        timeout: float = 15.0,
    ) -> Dict[str, Any]:
        helpers = self._ensure_ready()
        target_id = helpers.new_tab(url)
        loaded = helpers.wait_for_load(timeout=timeout) if wait else None
        info = helpers.page_info()
        result = {
            "result": "Opened browser tab",
            "target_id": target_id,
            "loaded": loaded,
            "page_info": info,
            "backend": "browser-harness",
            "identity": self.identity(),
        }
        domain_url = info.get("url") if isinstance(info, dict) else None
        result["domain_skills"] = self.domain_skill_matches(domain_url or url)
        return result

    def page_info(self) -> Dict[str, Any]:
        helpers = self._ensure_ready()
        info = helpers.page_info()
        return {
            "result": "Browser page info",
            "page_info": info,
            "domain_skills": self.domain_skill_matches(info.get("url", "")),
            "backend": "browser-harness",
            "identity": self.identity(),
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

    def click(
        self,
        x: float,
        y: float,
        button: str = "left",
        clicks: int = 1,
        return_page_info: bool = True,
    ) -> Dict[str, Any]:
        helpers = self._ensure_ready()
        helpers.click_at_xy(x, y, button=button, clicks=clicks)
        result: Dict[str, Any] = {
            "result": "Clicked browser coordinates",
            "x": x,
            "y": y,
            "button": button,
            "clicks": clicks,
            "backend": "browser-harness",
        }
        if return_page_info:
            result["page_info"] = helpers.page_info()
        return result

    def type_text(self, text: str) -> Dict[str, Any]:
        helpers = self._ensure_ready()
        helpers.type_text(text)
        return {
            "result": "Typed text",
            "text_length": len(text),
            "backend": "browser-harness",
        }

    def press_key(self, key: str, modifiers: int = 0) -> Dict[str, Any]:
        helpers = self._ensure_ready()
        helpers.press_key(key, modifiers=modifiers)
        return {
            "result": "Pressed key",
            "key": key,
            "modifiers": modifiers,
            "backend": "browser-harness",
        }

    def fill_input(
        self,
        selector: str,
        text: str,
        clear_first: bool = True,
        timeout: float = 0.0,
    ) -> Dict[str, Any]:
        helpers = self._ensure_ready()
        helpers.fill_input(
            selector,
            text,
            clear_first=clear_first,
            timeout=timeout,
        )
        return {
            "result": "Filled input",
            "selector": selector,
            "text_length": len(text),
            "clear_first": clear_first,
            "backend": "browser-harness",
        }

    def wait(
        self,
        mode: str = "load",
        timeout: float = 15.0,
        selector: Optional[str] = None,
        visible: bool = False,
        idle_ms: int = 500,
        seconds: Optional[float] = None,
    ) -> Dict[str, Any]:
        helpers = self._ensure_ready()
        if mode == "load":
            ok = helpers.wait_for_load(timeout=timeout)
        elif mode == "element":
            if not selector:
                return {"error": "browser_wait mode='element' requires selector"}
            ok = helpers.wait_for_element(
                selector,
                timeout=timeout,
                visible=visible,
            )
        elif mode == "network_idle":
            ok = helpers.wait_for_network_idle(timeout=timeout, idle_ms=idle_ms)
        elif mode == "sleep":
            duration = seconds if seconds is not None else timeout
            helpers.wait(duration)
            ok = True
        else:
            return {
                "error": (
                    "browser_wait mode must be one of: "
                    "load, element, network_idle, sleep"
                )
            }
        return {
            "result": "Wait completed" if ok else "Wait timed out",
            "ok": bool(ok),
            "mode": mode,
            "timeout": timeout,
            "backend": "browser-harness",
        }

    def js(
        self,
        expression: str,
        target_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        helpers = self._ensure_ready()
        value = helpers.js(expression, target_id=target_id)
        return {
            "result": "JavaScript evaluated",
            "value": value,
            "backend": "browser-harness",
        }

    def list_tabs(self, include_chrome: bool = False) -> Dict[str, Any]:
        helpers = self._ensure_ready()
        tabs = helpers.list_tabs(include_chrome=include_chrome)
        current = helpers.current_tab()
        return {
            "result": "Listed browser tabs",
            "tabs": tabs,
            "current_tab": current,
            "backend": "browser-harness",
        }

    def switch_tab(self, target_id: str) -> Dict[str, Any]:
        helpers = self._ensure_ready()
        session_id = helpers.switch_tab(target_id)
        return {
            "result": "Switched browser tab",
            "target_id": target_id,
            "session_id": session_id,
            "page_info": helpers.page_info(),
            "backend": "browser-harness",
        }


class BrowserHarnessStatusTool:
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}

    def execute(self, include_page: bool = True) -> Dict[str, Any]:
        return _runtime_adapter(self.config).status(include_page=include_page)


def _runtime_adapter(config: Optional[Dict[str, Any]] = None) -> BrowserHarnessAdapter:
    return BrowserHarnessAdapter(
        config=config,
        execution_context=get_current_execution_context_dict(),
    )


class BrowserHarnessOpenTabTool:
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}

    def execute(
        self,
        url: str,
        wait: bool = True,
        timeout: float = 15.0,
    ) -> Dict[str, Any]:
        return _runtime_adapter(self.config).open_tab(
            url=url,
            wait=wait,
            timeout=timeout,
        )


class BrowserHarnessPageInfoTool:
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}

    def execute(self) -> Dict[str, Any]:
        return _runtime_adapter(self.config).page_info()


class BrowserHarnessScreenshotTool:
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}

    def execute(
        self,
        full: bool = False,
        max_dim: Optional[int] = None,
        output_dir: Optional[str] = None,
    ) -> Dict[str, Any]:
        return _runtime_adapter(self.config).screenshot(
            full=full,
            max_dim=max_dim,
            output_dir=output_dir,
        )


class BrowserHarnessClickTool:
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}

    def execute(
        self,
        x: float,
        y: float,
        button: str = "left",
        clicks: int = 1,
        return_page_info: bool = True,
    ) -> Dict[str, Any]:
        return _runtime_adapter(self.config).click(
            x,
            y,
            button,
            clicks,
            return_page_info,
        )


class BrowserHarnessTypeTool:
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}

    def execute(self, text: str) -> Dict[str, Any]:
        return _runtime_adapter(self.config).type_text(text)


class BrowserHarnessKeyTool:
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}

    def execute(self, key: str, modifiers: int = 0) -> Dict[str, Any]:
        return _runtime_adapter(self.config).press_key(key, modifiers=modifiers)


class BrowserHarnessFillTool:
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}

    def execute(
        self,
        selector: str,
        text: str,
        clear_first: bool = True,
        timeout: float = 0.0,
    ) -> Dict[str, Any]:
        return _runtime_adapter(self.config).fill_input(
            selector,
            text,
            clear_first,
            timeout,
        )


class BrowserHarnessWaitTool:
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}

    def execute(
        self,
        mode: str = "load",
        timeout: float = 15.0,
        selector: Optional[str] = None,
        visible: bool = False,
        idle_ms: int = 500,
        seconds: Optional[float] = None,
    ) -> Dict[str, Any]:
        return _runtime_adapter(self.config).wait(
            mode,
            timeout,
            selector,
            visible,
            idle_ms,
            seconds,
        )


class BrowserHarnessJsTool:
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}

    def execute(
        self,
        expression: str,
        target_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        return _runtime_adapter(self.config).js(expression, target_id=target_id)


class BrowserHarnessListTabsTool:
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}

    def execute(self, include_chrome: bool = False) -> Dict[str, Any]:
        return _runtime_adapter(self.config).list_tabs(include_chrome=include_chrome)


class BrowserHarnessSwitchTabTool:
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}

    def execute(self, target_id: str) -> Dict[str, Any]:
        return _runtime_adapter(self.config).switch_tab(target_id=target_id)


__all__ = [
    "BrowserHarnessAdapter",
    "BrowserHarnessClickTool",
    "BrowserHarnessFillTool",
    "BrowserHarnessJsTool",
    "BrowserHarnessKeyTool",
    "BrowserHarnessListTabsTool",
    "BrowserHarnessOpenTabTool",
    "BrowserHarnessPageInfoTool",
    "BrowserHarnessScreenshotTool",
    "BrowserHarnessStatusTool",
    "BrowserHarnessSwitchTabTool",
    "BrowserHarnessTypeTool",
    "BrowserHarnessUnavailableError",
    "BrowserHarnessWaitTool",
]
