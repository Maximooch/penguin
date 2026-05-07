"""Optional browser-harness backend tools.

This module is intentionally import-safe when browser-harness is not installed.
The actual browser_harness package is imported lazily at execution time so
Penguin's base install and Python 3.9/3.10 users are not penalized.
"""
from __future__ import annotations

import datetime
import importlib
import importlib.metadata
import importlib.util
import os
import re
import socket
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from penguin.system.execution_context import get_current_execution_context_dict
from penguin.tools.browser_harness_ownership import BrowserHarnessOwnershipStore

_HELPERS_LOCK = threading.RLock()


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
        self.execution_context = (
            execution_context or get_current_execution_context_dict()
        )

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

    @property
    def ownership_path(self) -> str:
        value = self.config.get("ownership_path")
        if value:
            return str(Path(str(value)).expanduser())
        return str(BrowserHarnessOwnershipStore.default_path())

    @property
    def ownership_store(self) -> BrowserHarnessOwnershipStore:
        return BrowserHarnessOwnershipStore(self.ownership_path)

    @staticmethod
    def _distribution_version(*names: str) -> Optional[str]:
        for name in names:
            try:
                return importlib.metadata.version(name)
            except importlib.metadata.PackageNotFoundError:
                continue
        return None

    @staticmethod
    def _find_package_path(package_name: str) -> Optional[str]:
        try:
            spec = importlib.util.find_spec(package_name)
        except (ModuleNotFoundError, ValueError):
            spec = None
        if spec is None:
            return None
        if spec.submodule_search_locations:
            return str(next(iter(spec.submodule_search_locations)))
        return str(spec.origin) if spec.origin else None

    def backend_diagnostics(self) -> Dict[str, Any]:
        harness_path = self._find_package_path("browser_harness")
        pydoll_path = self._find_package_path("pydoll")
        return {
            "contract": "penguin-browser-tools-v1",
            "selected_backend": "browser-harness",
            "selected_backend_importable": harness_path is not None,
            "browser_harness": {
                "importable": harness_path is not None,
                "package_path": harness_path,
                "version": self._distribution_version(
                    "browser-harness", "browser_harness"
                ),
                "pypi_published": False,
                "python_requires": (
                    ">=3.11 for browser-harness; Penguin supports >=3.9,<3.13"
                ),
                "install_hint": (
                    "browser-harness is not published on PyPI. Install "
                    "penguin-ai[browser] for the PyDoll fallback, then install "
                    "browser-harness from a local checkout/source tree into the "
                    "same environment."
                ),
            },
            "pydoll_fallback": {
                "importable": pydoll_path is not None,
                "package_path": pydoll_path,
                "version": self._distribution_version("pydoll-python", "pydoll"),
                "tool_prefix": "pydoll_browser_*",
            },
        }

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
        if self.config.get("cdp_url"):
            env["BU_CDP_URL"] = str(self.config["cdp_url"])
        if self.config.get("cdp_ws"):
            env["BU_CDP_WS"] = str(self.config["cdp_ws"])
        if self.config.get("tmp_dir"):
            env["BH_TMP_DIR"] = str(Path(str(self.config["tmp_dir"])).expanduser())
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
            expected_name = (env or {}).get("BU_NAME")
            if (
                expected_name
                and getattr(admin, "NAME", expected_name) != expected_name
            ):
                admin = importlib.reload(admin)
            if (
                expected_name
                and getattr(helpers, "NAME", expected_name) != expected_name
            ):
                helpers = importlib.reload(helpers)
        except ModuleNotFoundError as exc:
            raise BrowserHarnessUnavailableError(
                "browser-harness is not installed. It is not published on PyPI; "
                "install `penguin-ai[browser]` for the PyDoll fallback, then "
                "install browser-harness from a local checkout/source tree into "
                "the same environment."
            ) from exc

        return admin, helpers

    def _ensure_ready_unlocked(self):
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
        if self.started_by_penguin:
            self.ownership_store.record_started(self.identity())
        return helpers

    def _ensure_ready(self):
        with _HELPERS_LOCK:
            return self._ensure_ready_unlocked()

    def identity(self) -> Dict[str, Any]:
        return {
            "backend": "browser-harness",
            "bu_name": self.name,
            "session_id": self.session_id,
            "agent_id": self.agent_id,
            "skills_dir": self.skills_dir,
            "domain_skills_enabled": self.domain_skills_enabled,
            "started_by_penguin": self.started_by_penguin,
            "ownership_path": self.ownership_path,
            "env": self._base_env(),
        }

    def status(self, include_page: bool = True) -> Dict[str, Any]:
        ownership_record = self.ownership_store.get(self.name)
        payload: Dict[str, Any] = {
            "result": "Browser harness status",
            "identity": self.identity(),
            "ownership": {
                "owned_by_penguin": bool(
                    ownership_record and ownership_record.get("started_by_penguin")
                ),
                "record": ownership_record,
                "path": self.ownership_path,
            },
            "python": {"executable": os.sys.executable},
            "host": {"hostname": socket.gethostname()},
            "backend": self.backend_diagnostics(),
        }
        try:
            with _HELPERS_LOCK:
                helpers = self._ensure_ready_unlocked()
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

    def cleanup(
        self,
        owned_only: bool = True,
        force: bool = False,
        name: Optional[str] = None,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        target_name = _slug(name or self.name)
        record = self.ownership_store.get(target_name)
        owned_by_penguin = bool(record and record.get("started_by_penguin"))

        if owned_only and not owned_by_penguin:
            return {
                "error": (
                    "Refusing to clean up browser-harness daemon without "
                    "Penguin ownership record"
                ),
                "target": target_name,
                "owned_only": owned_only,
                "owned_by_penguin": False,
                "ownership_path": self.ownership_path,
            }

        if not owned_by_penguin and not force:
            return {
                "error": (
                    "Refusing to clean up non-owned browser-harness daemon "
                    "without force=true"
                ),
                "target": target_name,
                "owned_only": owned_only,
                "owned_by_penguin": False,
                "ownership_path": self.ownership_path,
            }

        if dry_run:
            return {
                "result": "Browser cleanup dry run",
                "target": target_name,
                "would_cleanup": True,
                "owned_by_penguin": owned_by_penguin,
                "record": record,
                "ownership_path": self.ownership_path,
            }

        env = self._base_env()
        env["BU_NAME"] = target_name
        admin, _helpers = self._load_modules(env)
        try:
            admin.restart_daemon(target_name)
        except Exception as exc:
            return {
                "error": (
                    "Failed to clean up browser-harness daemon "
                    f"{target_name}: {exc}"
                ),
                "target": target_name,
                "owned_by_penguin": owned_by_penguin,
                "ownership_path": self.ownership_path,
            }

        removed = self.ownership_store.remove(target_name)
        return {
            "result": "Browser harness daemon cleanup completed",
            "target": target_name,
            "owned_by_penguin": owned_by_penguin,
            "removed_record": removed,
            "ownership_path": self.ownership_path,
        }

    def open_tab(
        self,
        url: str,
        wait: bool = True,
        timeout: float = 15.0,
    ) -> Dict[str, Any]:
        with _HELPERS_LOCK:
            helpers = self._ensure_ready_unlocked()
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
        with _HELPERS_LOCK:
            helpers = self._ensure_ready_unlocked()
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
        directory = Path(
            output_dir
            or self.config.get("screenshot_dir")
            or Path.cwd() / "screenshots"
        )
        directory.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        filepath = directory / f"browser_harness_screenshot_{timestamp}.png"
        resolved_max_dim = self.screenshot_max_dim if max_dim is None else max_dim

        with _HELPERS_LOCK:
            helpers = self._ensure_ready_unlocked()
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
        with _HELPERS_LOCK:
            helpers = self._ensure_ready_unlocked()
            helpers.click_at_xy(x, y, button=button, clicks=clicks)
            page_info = helpers.page_info() if return_page_info else None
        result: Dict[str, Any] = {
            "result": "Clicked browser coordinates",
            "x": x,
            "y": y,
            "button": button,
            "clicks": clicks,
            "backend": "browser-harness",
        }
        if return_page_info:
            result["page_info"] = page_info
        return result

    def type_text(self, text: str) -> Dict[str, Any]:
        with _HELPERS_LOCK:
            helpers = self._ensure_ready_unlocked()
            helpers.type_text(text)
        return {
            "result": "Typed text",
            "text_length": len(text),
            "backend": "browser-harness",
        }

    def press_key(self, key: str, modifiers: int = 0) -> Dict[str, Any]:
        with _HELPERS_LOCK:
            helpers = self._ensure_ready_unlocked()
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
        with _HELPERS_LOCK:
            helpers = self._ensure_ready_unlocked()
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
        with _HELPERS_LOCK:
            helpers = self._ensure_ready_unlocked()
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
        with _HELPERS_LOCK:
            helpers = self._ensure_ready_unlocked()
            value = helpers.js(expression, target_id=target_id)
        return {
            "result": "JavaScript evaluated",
            "value": value,
            "backend": "browser-harness",
        }

    def list_tabs(self, include_chrome: bool = False) -> Dict[str, Any]:
        with _HELPERS_LOCK:
            helpers = self._ensure_ready_unlocked()
            tabs = helpers.list_tabs(include_chrome=include_chrome)
            current = helpers.current_tab()
        return {
            "result": "Listed browser tabs",
            "tabs": tabs,
            "current_tab": current,
            "backend": "browser-harness",
        }

    def switch_tab(self, target_id: str) -> Dict[str, Any]:
        with _HELPERS_LOCK:
            helpers = self._ensure_ready_unlocked()
            session_id = helpers.switch_tab(target_id)
            info = helpers.page_info()
        return {
            "result": "Switched browser tab",
            "target_id": target_id,
            "session_id": session_id,
            "page_info": info,
            "backend": "browser-harness",
        }


class BrowserHarnessStatusTool:
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}

    def execute(self, include_page: bool = True) -> Dict[str, Any]:
        return _runtime_adapter(self.config).status(include_page=include_page)


class BrowserHarnessCleanupTool:
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}

    def execute(
        self,
        owned_only: bool = True,
        force: bool = False,
        name: Optional[str] = None,
        dry_run: bool = False,
    ) -> Dict[str, Any]:
        return _runtime_adapter(self.config).cleanup(
            owned_only=owned_only,
            force=force,
            name=name,
            dry_run=dry_run,
        )


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
