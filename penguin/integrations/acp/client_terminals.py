"""Bounded foreground commands through the ACP client's terminal lifecycle."""

import asyncio
import contextlib
import copy
import json
import logging
import math
import os
from typing import Any
from uuid import uuid4

from acp.helpers import text_block
from acp.schema import (
    ContentToolCallContent,
    EnvVariable,
    TerminalToolCallContent,
    ToolCallProgress,
    ToolCallStart,
)

from penguin.integrations.acp.client_files import ClientFiles
from penguin.security.scoped_paths import enforce_execution_path
from penguin.system.tool_environment import build_tool_environment

DEFAULT_SHELL = "cmd" if os.name == "nt" else "sh"
logger = logging.getLogger(__name__)


class ClientTerminals(ClientFiles):
    supports_terminal = True

    def __init__(self, owner: Any, root: str, shell: str) -> None:
        super().__init__(owner, root)
        self.shell = shell

    def schema(self, schema: dict[str, Any]) -> dict[str, Any] | None:
        if schema.get("name") != "execute_command":
            return super().schema(schema)
        result = copy.deepcopy(schema)
        result["description"] = (
            "Run a foreground command in the ACP client's terminal. Waits for exit; "
            "maximum 600 seconds. No background process handle is returned."
        )
        result["input_schema"]["properties"].pop("yield_time_ms", None)
        return result

    async def execute(
        self, name: str, args: dict[str, Any], context: dict[str, Any]
    ) -> str:
        if name != "execute_command":
            return await super().execute(name, args, context)
        from pathlib import Path

        if self.owner._closed or self.root not in self.owner.sessions:
            return json.dumps({"error": "client_session_closed"})
        if "yield_time_ms" in args:
            return json.dumps({"error": "client_terminal_does_not_yield"})
        command = args.get("command")
        timeout = args.get("timeout_seconds", 60)
        max_chars = args.get("max_chars", 12000)
        if (
            not isinstance(command, str)
            or not command
            or "\0" in command
            or isinstance(timeout, bool)
            or not isinstance(timeout, (int, float))
            or not math.isfinite(timeout)
            or not 0 < timeout <= 600
            or type(max_chars) is not int
            or max_chars < 0
        ):
            return json.dumps({"error": "invalid_client_terminal_command_or_timeout"})
        overrides = args.get("env") or {}
        try:
            build_tool_environment(
                overrides
            )  # Validate; never forward host/trusted environment.
            cwd = enforce_execution_path(Path(args.get("cwd") or context["directory"]))
        except (TypeError, ValueError, AttributeError):
            return json.dumps({"error": "invalid_client_terminal_environment_or_cwd"})
        executable, shell_args = {
            "cmd": ("cmd.exe", ["/d", "/s", "/c", command]),
            "pwsh": (
                "pwsh",
                ["-NoLogo", "-NoProfile", "-NonInteractive", "-Command", command],
            ),
            "sh": ("sh", ["-c", command]),
        }[self.shell]
        sid = context.get("session_id") or self.root
        child = self.owner._children.children.get(sid)
        target = sid if child and self.owner._children.native else self.root
        conn = self.owner._connection
        terminal_id = None
        call_id = "terminal:" + uuid4().hex
        created = asyncio.create_task(
            conn.create_terminal(
                session_id=target,
                command=executable,
                args=shell_args,
                cwd=str(cwd),
                env=[EnvVariable(name=k, value=v) for k, v in overrides.items()],
                output_byte_limit=65536,
            )
        )
        completed = False
        announced = False
        response = {}
        cleanup_errors = []
        try:
            terminal = await asyncio.wait_for(asyncio.shield(created), 10)
            terminal_id = terminal.terminal_id
            await self.owner._send_update(
                sid,
                ToolCallStart(
                    session_update="tool_call",
                    tool_call_id=call_id,
                    kind="execute",
                    title="Client terminal",
                    status="in_progress",
                    content=[
                        TerminalToolCallContent(
                            type="terminal", terminal_id=terminal_id
                        )
                    ],
                ),
            )
            announced = True
            status = await asyncio.wait_for(
                conn.wait_for_terminal_exit(session_id=target, terminal_id=terminal_id),
                timeout,
            )
            output = await asyncio.wait_for(
                conn.terminal_output(session_id=target, terminal_id=terminal_id), 10
            )
            completed = True
            content = output.output[: min(max_chars, 65536)]
            await self.owner._send_update(
                sid,
                ToolCallProgress(
                    session_update="tool_call_update",
                    tool_call_id=call_id,
                    status="completed" if status.exit_code == 0 else "failed",
                    content=[
                        ContentToolCallContent(
                            type="content", content=text_block(content)
                        )
                    ],
                ),
            )
            response = {
                "status": "completed" if status.exit_code == 0 else "error",
                "output": content,
                "returncode": status.exit_code,
                "signal": status.signal,
                "truncated": output.truncated or len(content) < len(output.output),
                "execution_host": "client",
            }
        except asyncio.CancelledError:
            raise
        except asyncio.TimeoutError:
            response = {"error": "client_terminal_timeout", "execution_host": "client"}
        except Exception:
            response = {"error": "client_terminal_failed", "execution_host": "client"}
        finally:

            async def cleanup():
                nonlocal terminal_id
                if terminal_id is None:
                    with contextlib.suppress(Exception, asyncio.CancelledError):
                        result = await asyncio.wait_for(asyncio.shield(created), 10)
                        terminal_id = result.terminal_id
                if terminal_id is not None:
                    if not completed:
                        if announced:
                            with contextlib.suppress(Exception):
                                await self.owner._send_update(
                                    sid,
                                    ToolCallProgress(
                                        session_update="tool_call_update",
                                        tool_call_id=call_id,
                                        status="failed",
                                        content=[
                                            ContentToolCallContent(
                                                type="content",
                                                content=text_block(
                                                    "Client terminal interrupted "
                                                    "or failed"
                                                ),
                                            )
                                        ],
                                    ),
                                )
                        try:
                            await asyncio.wait_for(
                                conn.kill_terminal(
                                    session_id=target, terminal_id=terminal_id
                                ),
                                5,
                            )
                        except Exception:
                            cleanup_errors.append("kill_failed")
                    try:
                        await asyncio.wait_for(
                            conn.release_terminal(
                                session_id=target, terminal_id=terminal_id
                            ),
                            5,
                        )
                    except Exception:
                        cleanup_errors.append("release_failed")
                else:
                    cleanup_errors.append("terminal_creation_outcome_unknown")
                if not created.done():
                    created.cancel()

            await asyncio.shield(cleanup())
            if cleanup_errors:
                logger.warning("Client terminal cleanup incomplete: %s", cleanup_errors)
        if cleanup_errors:
            response["cleanup_errors"] = cleanup_errors
        return json.dumps(response)
