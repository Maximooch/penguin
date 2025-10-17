from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

import httpx  # type: ignore

from penguin.tools.tool_manager import ToolManager


class MCPClientBridge:
    """Discover tools from remote MCP HTTP servers and register as virtual tools.

    For simplicity, this MVP supports HTTP transport. Each remote tool is exposed
    as a new ToolManager tool named `mcp::<server>::<tool>` with the original
    schema, and calls are proxied to the remote server.
    """

    def __init__(self, servers: List[Dict[str, Any]]):
        self.servers = servers or []

    def _http_list(self, url: str, token: Optional[str]) -> List[Dict[str, Any]]:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(url.rstrip("/") + "/api/v1/mcp/tools", headers=headers)
            resp.raise_for_status()
            payload = resp.json()
            return list(payload.get("tools", []))

    def _http_call(self, base_url: str, token: Optional[str], tool: str, params: Dict[str, Any]) -> Any:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        with httpx.Client(timeout=60.0) as client:
            resp = client.post(base_url.rstrip("/") + f"/api/v1/mcp/tools/{tool}:call", json={"params": params, "confirm": False}, headers=headers)
            resp.raise_for_status()
            payload = resp.json()
            if payload.get("status") == "ok":
                return payload.get("data")
            raise RuntimeError(str(payload.get("error")))

    def register_remote_tools(self, tm: ToolManager) -> None:
        for server_conf in self.servers:
            if (server_conf or {}).get("transport") != "http":
                continue
            base_url = str(server_conf.get("url"))
            token = server_conf.get("auth", {}).get("token") if isinstance(server_conf.get("auth"), dict) else None
            name = str(server_conf.get("name") or base_url)
            try:
                tools = self._http_list(base_url, token)
            except Exception:
                continue
            for spec in tools:
                tool_name = str(spec.get("name"))
                local_name = f"mcp::{name}::{tool_name}"

                # Append schema so LLMs can see virtual tools
                tm.tools.append(
                    {
                        "name": local_name,
                        "description": spec.get("description", f"Remote MCP tool {tool_name}"),
                        "input_schema": spec.get("input_schema") or {"type": "object", "properties": {}},
                    }
                )

                # Create a bound method on ToolManager that proxies the call
                def _make_proxy(_url: str, _token: Optional[str], _rname: str):
                    def _proxy(**kwargs):
                        return self._http_call(_url, _token, _rname, kwargs)
                    return _proxy

                attr_name = f"_mcp_proxy_{name}_{tool_name}".replace("-", "_").replace(":", "_")
                setattr(tm, attr_name, _make_proxy(base_url, token, tool_name))
                # Link to registry
                registry = getattr(tm, "_tool_registry", {})
                registry[local_name] = f"self.{attr_name}"


