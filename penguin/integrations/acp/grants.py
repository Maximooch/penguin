"""Exact-resource ACP grants, never broad native session approvals."""

import hashlib
import json
from pathlib import Path
from typing import Any

from acp.schema import PermissionOption


class ExactGrants:
    def __init__(self, owner: Any) -> None:
        self.owner = owner
        self.volatile: dict[str, list[dict[str, Any]]] = {}
        self.saved: dict[str, list[dict[str, Any]]] = {}

    def key(self, request: Any) -> dict[str, Any] | None:
        if request.operation not in {"filesystem.read", "filesystem.write"}:
            return None
        try:
            path = Path(request.resource)
            valid = (
                path.is_absolute()
                and str(path.resolve()) == request.resource
                and any(
                    path.is_relative_to(root)
                    for root in self.owner._roots_for(request.session_id)
                )
            )
        except (ValueError, OSError, RuntimeError):
            return None
        if not valid:
            return None
        policy = {
            k: request.context.get(k) for k in ("permission_mode", "approval_policy")
        }
        child = self.owner._children.children.get(request.session_id)
        session = self.owner.sessions.get(child.root if child else request.session_id)
        return {
            "tool": request.tool_name,
            "operation": request.operation,
            "resource": request.resource,
            "agent": request.context.get("agent_id") or "agent",
            "mode": request.context.get("agent_mode"),
            "policy": hashlib.sha256(
                json.dumps(policy, sort_keys=True, default=str).encode()
            ).hexdigest(),
            "roots": [str(root) for root in self.owner._roots_for(request.session_id)],
            "backend": session.filesystem if session else "local",
        }

    def options(self, request: Any) -> list[PermissionOption]:
        options = [
            PermissionOption(
                option_id="allow_once", name="Allow once", kind="allow_once"
            )
        ]
        if self.key(request) is not None:
            options.append(
                PermissionOption(
                    option_id="allow_session",
                    name="Allow this exact resource until session closes",
                    kind="allow_always",
                )
            )
            if (
                request.session_id in self.owner.sessions
                and self.owner._registry.available
            ):
                options.append(
                    PermissionOption(
                        option_id="allow_saved",
                        name="Remember this exact resource for this saved session",
                        kind="allow_always",
                    )
                )
        options.append(
            PermissionOption(option_id="reject_once", name="Reject", kind="reject_once")
        )
        return options

    def allows(self, request: Any) -> bool:
        key = self.key(request)
        return key is not None and key in (
            self.volatile.get(request.session_id, [])
            + self.saved.get(request.session_id, [])
        )

    def remember(self, request: Any, persistent: bool) -> None:
        key = self.key(request)
        if key is None:
            return
        target = self.saved if persistent else self.volatile
        grants = [g for g in target.get(request.session_id, []) if g != key]
        grants = [*grants[-127:], key]
        if persistent:
            session = self.owner._registry.get(request.session_id)
            previous = session.metadata.get("acp_exact_grants_v1")
            session.metadata["acp_exact_grants_v1"] = grants
            try:
                self.owner._registry.save(session)
            except Exception:
                if previous is None:
                    session.metadata.pop("acp_exact_grants_v1", None)
                else:
                    session.metadata["acp_exact_grants_v1"] = previous
                raise
        target[request.session_id] = grants

    def restore(self, sid: str, session: Any) -> None:
        self.close(sid)
        raw = session.metadata.get("acp_exact_grants_v1", [])
        if isinstance(raw, list):
            keys = {
                "tool",
                "operation",
                "resource",
                "agent",
                "mode",
                "policy",
                "roots",
                "backend",
            }
            self.saved[sid] = [
                g
                for g in raw[:128]
                if isinstance(g, dict)
                and set(g) == keys
                and g.get("operation") in {"filesystem.read", "filesystem.write"}
                and all(
                    isinstance(g.get(k), str)
                    for k in ("tool", "resource", "agent", "policy")
                )
                and isinstance(g.get("roots"), list)
                and g.get("backend") in {"local", "client"}
            ]

    def close(self, sid: str) -> None:
        self.volatile.pop(sid, None)
        self.saved.pop(sid, None)

    def reset(self, sid: str) -> None:
        self.close(sid)
        for child_id, child in self.owner._children.children.items():
            if child.root == sid:
                self.close(child_id)
        if self.owner._registry.available:
            session = self.owner._registry.get(sid)
            session.metadata.pop("acp_exact_grants_v1", None)
            self.owner._registry.save(session)
