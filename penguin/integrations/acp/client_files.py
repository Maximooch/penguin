"""Opt-in text-file access through the negotiated ACP client."""

import asyncio
import copy
import json
from pathlib import Path
from typing import Any

from penguin.security.scoped_paths import enforce_execution_path
from penguin.security.tool_permissions import get_tool_operations
from penguin.tools.process_tools import PROCESS_TOOL_NAMES


class ClientFiles:
    supported = frozenset({"read_file", "write_file", "write_to_file"})

    def __init__(self, owner: Any, root: str) -> None:
        self.owner, self.root = owner, root

    def handles(self, name: str) -> bool:
        return name in PROCESS_TOOL_NAMES or any(
            op.category in {"filesystem", "process"} for op in get_tool_operations(name)
        )

    def schema(self, schema: dict[str, Any]) -> dict[str, Any] | None:
        name = schema.get("name", "")
        if not self.handles(name):
            return schema
        if name not in self.supported:
            return None
        result = copy.deepcopy(schema)
        result["description"] += " Uses the ACP client's text buffer."
        if name in {"write_file", "write_to_file"}:
            result["input_schema"]["properties"].pop("backup", None)
            result["description"] += (
                " Replaces content; client API provides no backup guarantee."
            )
        return result

    async def execute(
        self, name: str, args: dict[str, Any], context: dict[str, Any]
    ) -> str:
        if self.owner._closed or self.root not in self.owner.sessions:
            return json.dumps({"error": "client_session_closed"})
        if name not in self.supported:
            return json.dumps(
                {"error": "unsupported_client_file_operation", "tool": name}
            )
        target = self.root
        child = self.owner._children.children.get(context.get("session_id"))
        if child and self.owner._children.native:
            target = context["session_id"]
        path = enforce_execution_path(Path(args["path"]))
        try:
            if name == "read_file":
                limit = args.get("max_lines", 2000)
                if type(limit) is not int or limit <= 0:
                    raise ValueError("max_lines must be positive")
                response = await asyncio.wait_for(
                    self.owner._connection.read_text_file(
                        session_id=target,
                        path=str(path),
                        line=1,
                        limit=min(limit, 2000),
                    ),
                    30,
                )
                content = response.content
                if len(content.encode("utf-8")) > 2 * 1024 * 1024:
                    raise ValueError("Client text response exceeds 2 MiB")
                if args.get("show_line_numbers"):
                    content = "\n".join(
                        f"{i}: {line}" for i, line in enumerate(content.splitlines(), 1)
                    )
                return json.dumps(
                    {"status": "completed", "path": str(path), "content": content}
                )
            if args.get("backup"):
                raise ValueError("The client API cannot guarantee backup creation")
            content = args["content"]
            if (
                not isinstance(content, str)
                or len(content.encode("utf-8")) > 2 * 1024 * 1024
            ):
                raise ValueError("Client writes require text up to 2 MiB")
            await asyncio.wait_for(
                self.owner._connection.write_text_file(
                    session_id=target, path=str(path), content=content
                ),
                30,
            )
            return json.dumps(
                {
                    "status": "completed",
                    "path": str(path),
                    "result": "Client text written",
                }
            )
        except asyncio.CancelledError:
            raise
        except (ValueError, asyncio.TimeoutError) as exc:
            return json.dumps({"error": "client_filesystem_error", "reason": str(exc)})
        except Exception:
            return json.dumps(
                {"error": "client_filesystem_error", "reason": "Client request failed"}
            )
