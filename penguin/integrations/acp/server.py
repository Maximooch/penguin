"""Local editor-facing ACP v1 adapter. Optional dependency: penguin-ai[acp].

Only text prompts, new sessions, streaming text, permissions, and cancellation are
implemented. In particular, load and client-provided MCP are not advertised.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import uuid4

from acp import PROTOCOL_VERSION, RequestError, run_agent
from acp.helpers import text_block
from acp.interfaces import Client
from acp.schema import (
    AgentMessageChunk,
    ClientCapabilities,
    Implementation,
    InitializeResponse,
    NewSessionResponse,
    PermissionOption,
    PromptResponse,
    TextContentBlock,
    ToolCallStart,
)

from penguin._version import __version__
from penguin.security.approval import ApprovalRequest, ApprovalScope, ApprovalStatus, get_approval_manager
from penguin.system.execution_context import ExecutionContext, execution_context_scope

logger = logging.getLogger(__name__)


@dataclass
class Session:
    cwd: Path
    task: asyncio.Task[Any] | None = None
    cancelled: bool = False
    running: bool = False


class PenguinACPAgent:
    """Translate ACP requests into Penguin conversations and process calls.

    Penguin's conversation manager is shared, so process requests are serialized
    until concurrent conversation state is proven safe. An ACP session is still
    isolated by its conversation id and immutable directory context.
    """

    def __init__(self, core: Any, *, allowed_roots: tuple[Path, ...]) -> None:
        self.core = core
        self.allowed_roots = tuple(path.resolve() for path in allowed_roots)
        self.sessions: dict[str, Session] = {}
        self._process_gate = asyncio.Lock()
        self._connection: Client | None = None
        self._approval_tasks: set[asyncio.Task[Any]] = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._approvals = get_approval_manager()
        self._approvals.on_request_created(self._on_approval)

    def on_connect(self, conn: Client) -> None:
        self._connection = conn

    def close(self) -> None:
        self._approvals.remove_callback(self._on_approval)
        for task in self._approval_tasks:
            task.cancel()
        for sid in self.sessions:
            for request in self._approvals.get_pending(sid):
                self._approvals.deny(request.id)

    async def initialize(
        self,
        protocol_version: int,
        client_capabilities: ClientCapabilities | None = None,
        client_info: Implementation | None = None,
        **kwargs: Any,
    ) -> InitializeResponse:
        if protocol_version < PROTOCOL_VERSION:
            raise RequestError.invalid_params({"protocolVersion": protocol_version})
        self._loop = asyncio.get_running_loop()
        return InitializeResponse(
            protocol_version=PROTOCOL_VERSION,
            agent_info=Implementation(name="penguin", version=__version__),
        )

    async def new_session(
        self,
        cwd: str,
        additional_directories: list[str] | None = None,
        mcp_servers: list[Any] | None = None,
        **kwargs: Any,
    ) -> NewSessionResponse:
        if additional_directories or mcp_servers:
            raise RequestError.invalid_params({"reason": "Additional directories and MCP servers are not yet supported"})
        directory = Path(cwd).expanduser()
        if not directory.is_absolute() or not directory.is_dir():
            raise RequestError.invalid_params({"cwd": cwd})
        directory = directory.resolve()
        if not any(directory == root or root in directory.parents for root in self.allowed_roots):
            raise RequestError.invalid_params({"reason": "cwd is outside the authorized workspace"})
        # PenguinCore's create_conversation is synchronous, despite the web
        # interface's separate async convenience wrapper.
        sid = self.core.create_conversation()
        self.sessions[sid] = Session(cwd=directory)
        return NewSessionResponse(session_id=sid)

    async def prompt(self, session_id: str, prompt: list[Any], **kwargs: Any) -> PromptResponse:
        session = self.sessions.get(session_id)
        if session is None:
            raise RequestError.invalid_params({"sessionId": session_id})
        if session.task is not None:
            raise RequestError.invalid_request({"reason": "A turn is already active for this session"})
        if not prompt or any(not isinstance(block, TextContentBlock) for block in prompt):
            raise RequestError.invalid_params({"reason": "Only non-empty text prompts are supported"})
        if self._connection is None:
            raise RequestError.internal_error()
        session.task = asyncio.current_task()
        session.cancelled = False
        sent: list[str] = []

        async def on_chunk(chunk: str, message_type: str = "assistant") -> None:
            if session.cancelled or message_type != "assistant" or not chunk:
                return
            await self._connection.session_update(
                session_id=session_id,
                update=AgentMessageChunk(
                    content=text_block(chunk), session_update="agent_message_chunk"
                ),
            )
            sent.append(chunk)

        try:
            async with self._process_gate:
                if session.cancelled:
                    return PromptResponse(stop_reason="cancelled")
                session.running = True
                with execution_context_scope(
                    ExecutionContext(
                        session_id=session_id,
                        conversation_id=session_id,
                        directory=str(session.cwd),
                        project_root=str(session.cwd),
                        request_id=uuid4().hex,
                    )
                ):
                    result = await self.core.process(
                        "\n".join(block.text for block in prompt),
                        conversation_id=session_id,
                        streaming=True,
                        stream_callback=on_chunk,
                    )
            if session.cancelled or result.get("aborted"):
                return PromptResponse(stop_reason="cancelled")
            if result.get("error") or result.get("status") in {"error", "provider_error", "failed"}:
                raise RequestError.internal_error({"reason": "Penguin could not complete the turn"})
            text = result.get("assistant_response") or ""
            if text and not sent:
                await on_chunk(text)
            return PromptResponse(stop_reason="end_turn")
        except asyncio.CancelledError:
            session.cancelled = True
            return PromptResponse(stop_reason="cancelled")
        finally:
            if session.cancelled:
                for request in self._approvals.get_pending(session_id):
                    self._approvals.deny(request.id)
            session.running = False
            session.task = None

    async def cancel(self, session_id: str, **kwargs: Any) -> None:
        session = self.sessions.get(session_id)
        if session is None or session.task is None:
            return
        session.cancelled = True
        for request in self._approvals.get_pending(session_id):
            self._approvals.deny(request.id)
        # A queued turn has no Penguin execution to abort. Cancel it without
        # interrupting the other session that currently owns the process gate.
        if session.running:
            await self.core.abort_session(session_id)
        session.task.cancel()

    def _on_approval(self, request: ApprovalRequest) -> None:
        session = self.sessions.get(request.session_id)
        if session is None or self._loop is None:
            return
        if session.cancelled:
            self._approvals.deny(request.id)
            return

        def schedule() -> None:
            task = self._loop.create_task(self._request_permission(request))
            self._approval_tasks.add(task)
            task.add_done_callback(self._approval_tasks.discard)

        self._loop.call_soon_threadsafe(schedule)

    async def _request_permission(self, request: ApprovalRequest) -> None:
        if self._connection is None or self._approvals.get_request(request.id) is None:
            self._approvals.deny(request.id)
            return
        try:
            response = await asyncio.wait_for(
                self._connection.request_permission(
                    session_id=request.session_id,
                    tool_call=ToolCallStart(
                        tool_call_id=request.id,
                        title=f"{request.tool_name}: {request.resource}",
                        session_update="tool_call",
                    ),
                    options=[
                        PermissionOption(option_id="allow_once", name="Allow once", kind="allow_once"),
                        PermissionOption(option_id="reject_once", name="Reject", kind="reject_once"),
                    ],
                ),
                timeout=300,
            )
            current = self._approvals.get_request(request.id)
            session = self.sessions[request.session_id]
            if (
                current is not None
                and current.status == ApprovalStatus.PENDING
                and not session.cancelled
                and response.outcome.outcome == "selected"
                and response.outcome.option_id == "allow_once"
            ):
                self._approvals.approve(request.id, scope=ApprovalScope.ONCE)
            else:
                self._approvals.deny(request.id)
        except asyncio.CancelledError:
            self._approvals.deny(request.id)
            raise
        except Exception:
            logger.warning("ACP permission request failed; denying", exc_info=True)
            self._approvals.deny(request.id)


async def serve() -> None:
    from acp.stdio import stdio_streams

    from penguin.config import WORKSPACE_PATH
    from penguin.core import PenguinCore

    # ACP owns stdout. Startup code and provider libraries may print; keep their
    # output on stderr for the entire lifetime of the agent. Bind the SDK's
    # protocol writer to the real stdout pipe before redirecting Python prints.
    sys.stdout = sys.stderr
    core = await PenguinCore.create(show_progress=False)
    protocol_stdout = sys.__stdout__
    sys.stdout = protocol_stdout
    try:
        reader, writer = await stdio_streams()
    finally:
        sys.stdout = sys.stderr
    roots = (Path.cwd(), Path(WORKSPACE_PATH))
    agent = PenguinACPAgent(core, allowed_roots=roots)
    try:
        await run_agent(agent, input_stream=writer, output_stream=reader)
    finally:
        agent.close()


def main() -> int:
    logging.basicConfig(stream=sys.stderr)
    asyncio.run(serve())
    return 0
