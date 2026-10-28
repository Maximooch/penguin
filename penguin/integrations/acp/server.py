"""Local editor-facing ACP v1 adapter. Optional dependency: penguin-ai[acp].

Text/resource-reference prompts, new sessions, streaming text, permissions, and
cancellation are implemented. Load and client-provided MCP are not advertised.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from acp import PROTOCOL_VERSION, RequestError, run_agent
from acp.helpers import text_block
from acp.schema import (
    AgentCapabilities,
    AgentMessageChunk,
    ClientCapabilities,
    CloseSessionResponse,
    Implementation,
    InitializeResponse,
    ListSessionsResponse,
    LoadSessionResponse,
    McpCapabilities,
    NewSessionResponse,
    PermissionOption,
    PromptCapabilities,
    PromptResponse,
    ResumeSessionResponse,
    SessionCapabilities,
    SessionCloseCapabilities,
    SessionInfo,
    SessionListCapabilities,
    SessionResumeCapabilities,
    ToolCallStart,
    UserMessageChunk,
)

from penguin._version import __version__
from penguin.integrations.acp.content import prepare_prompt
from penguin.integrations.acp.events import EventBridge
from penguin.integrations.acp.mcp import session_provider
from penguin.integrations.acp.sessions import SessionRegistry
from penguin.integrations.mcp.manager import HAS_MCP_SDK
from penguin.security.approval import (
    ApprovalRequest,
    ApprovalScope,
    ApprovalStatus,
    get_approval_manager,
)
from penguin.system.execution_context import ExecutionContext, execution_context_scope
from penguin.tools.providers.mcp import mcp_provider_scope

if TYPE_CHECKING:
    from acp.interfaces import Client

logger = logging.getLogger(__name__)


@dataclass
class Session:
    cwd: Path
    task: asyncio.Task[Any] | None = None
    cancelled: bool = False
    running: bool = False
    mcp_provider: Any = None


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
        self._registry = SessionRegistry(core, self.allowed_roots)
        self._image_support = self._registry.available and bool(
            getattr(getattr(core, "model_config", None), "vision_enabled", False)
        )
        self._mcp_support = HAS_MCP_SDK and hasattr(core, "tool_manager")
        self._events = EventBridge(
            getattr(core, "event_bus", None), self._active_cwd, self._send_update
        )

    def _active_cwd(self, sid: str) -> Path | None:
        session = self.sessions.get(sid)
        return session.cwd if session and session.running else None

    async def _send_update(self, sid: str, update: Any) -> None:
        self._registry.record(sid, update)
        if self._connection is not None:
            await self._connection.session_update(session_id=sid, update=update)

    def on_connect(self, conn: Client) -> None:
        self._connection = conn

    def close(self) -> None:
        self._events.close()
        for session in self.sessions.values():
            if session.mcp_provider is not None:
                try:
                    session.mcp_provider.close()
                except Exception:
                    logger.warning("Could not close ACP MCP provider", exc_info=True)
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
            agent_capabilities=AgentCapabilities(
                mcp_capabilities=McpCapabilities(
                    http=self._mcp_support, sse=self._mcp_support
                ),
                prompt_capabilities=PromptCapabilities(
                    image=self._image_support, embedded_context=self._registry.available
                ),
                load_session=self._registry.available,
                session_capabilities=SessionCapabilities(
                    list=SessionListCapabilities()
                    if self._registry.available
                    else None,
                    resume=SessionResumeCapabilities()
                    if self._registry.available
                    else None,
                    close=SessionCloseCapabilities()
                    if self._registry.available
                    else None,
                ),
            ),
        )

    async def new_session(
        self,
        cwd: str,
        additional_directories: list[str] | None = None,
        mcp_servers: list[Any] | None = None,
        **kwargs: Any,
    ) -> NewSessionResponse:
        if additional_directories or (mcp_servers and not self._mcp_support):
            raise RequestError.invalid_params(
                {"reason": "Additional directories and MCP servers are unsupported"}
            )
        directory = Path(cwd).expanduser()
        if not directory.is_absolute() or not directory.is_dir():
            raise RequestError.invalid_params({"cwd": cwd})
        directory = directory.resolve()
        if not any(
            directory == root or root in directory.parents
            for root in self.allowed_roots
        ):
            raise RequestError.invalid_params(
                {"reason": "cwd is outside the authorized workspace"}
            )
        # PenguinCore's create_conversation is synchronous, despite the web
        # interface's separate async convenience wrapper.
        async with self._process_gate:
            provider = await self._new_mcp_provider(mcp_servers, directory)
            try:
                sid = self.core.create_conversation()
                self._registry.create(sid, directory)
                self.sessions[sid] = Session(cwd=directory, mcp_provider=provider)
            except BaseException:
                if provider is not None:
                    await asyncio.to_thread(provider.close)
                raise
        return NewSessionResponse(session_id=sid)

    async def _new_mcp_provider(self, servers: list[Any] | None, cwd: Path) -> Any:
        if not servers:
            return None
        if not self._mcp_support:
            raise RequestError.invalid_params({"reason": "Client MCP is unavailable"})
        provider = session_provider(servers, cwd, self.core.tool_manager.config)
        try:
            await asyncio.to_thread(provider.get_tool_schemas)
            if any(
                item["status"] != "connected"
                for item in provider.status()["servers"].values()
            ):
                raise RequestError.internal_error(
                    {"reason": "MCP server could not connect"}
                )
        except BaseException:
            await asyncio.to_thread(provider.close)
            raise
        return provider

    async def load_session(
        self,
        cwd: str,
        session_id: str,
        mcp_servers: list[Any] | None = None,
        additional_directories: list[str] | None = None,
        **kwargs: Any,
    ) -> LoadSessionResponse:
        """Restore only this adapter's sessions and replay before acknowledging."""
        await self._restore_session(
            cwd, session_id, mcp_servers, additional_directories, replay=True
        )
        return LoadSessionResponse()

    async def resume_session(
        self,
        cwd: str,
        session_id: str,
        mcp_servers: list[Any] | None = None,
        additional_directories: list[str] | None = None,
        **kwargs: Any,
    ) -> ResumeSessionResponse:
        """Restore context without sending historical updates again."""
        await self._restore_session(
            cwd, session_id, mcp_servers, additional_directories, replay=False
        )
        return ResumeSessionResponse()

    async def close_session(
        self, session_id: str, **kwargs: Any
    ) -> CloseSessionResponse:
        """Cancel active work and detach the session without deleting its history."""
        session = self.sessions.get(session_id)
        if session is None:
            raise RequestError.invalid_params({"reason": "Session is not open"})
        task = session.task
        if task is not None:
            await self.cancel(session_id)
            await asyncio.shield(task)
        if session.mcp_provider is not None:
            await asyncio.to_thread(session.mcp_provider.close)
        self.sessions.pop(session_id, None)
        return CloseSessionResponse()

    async def _restore_session(
        self,
        cwd: str,
        session_id: str,
        mcp_servers: list[Any] | None,
        additional_directories: list[str] | None,
        *,
        replay: bool,
    ) -> None:
        if additional_directories or (mcp_servers and not self._mcp_support):
            raise RequestError.invalid_params({"reason": "Unsupported session options"})
        if self._connection is None:
            raise RequestError.internal_error()
        active = self.sessions.get(session_id)
        if active and active.task is not None:
            raise RequestError.invalid_request({"reason": "Session is busy"})
        async with self._process_gate:
            saved = self._registry.get(session_id)
            owned_cwd = self._registry.cwd(saved)
            if (
                owned_cwd is None
                or Path(cwd).resolve() != owned_cwd
                or not Path(cwd).is_absolute()
            ):
                raise RequestError.invalid_params(
                    {"reason": "Session workspace does not match"}
                )
            history = self._registry.history(saved)
            provider = await self._new_mcp_provider(mcp_servers, owned_cwd)
            if active and active.mcp_provider is not None:
                await asyncio.to_thread(active.mcp_provider.close)
            self.sessions[session_id] = Session(cwd=owned_cwd, mcp_provider=provider)
            if replay:
                for update in history:
                    await self._connection.session_update(
                        session_id=session_id, update=update
                    )

    async def list_sessions(
        self, cwd: str | None = None, cursor: str | None = None, **kwargs: Any
    ) -> ListSessionsResponse:
        """List scoped ACP sessions with stable ID-based pagination."""
        if not self._registry.available:
            raise RequestError.method_not_found("session/list")
        if cursor is not None and not re.fullmatch(r"[A-Za-z0-9_-]+", cursor):
            raise RequestError.invalid_params({"reason": "Invalid cursor"})
        sessions = []
        async with self._process_gate:
            for sid in sorted(self._registry.store.session_index):
                if cursor and sid <= cursor:
                    continue
                saved = self._registry.get(sid)
                path = self._registry.cwd(saved)
                if path is None or (cwd is not None and str(path) != cwd):
                    continue
                sessions.append(
                    SessionInfo(
                        session_id=sid, cwd=str(path), updated_at=saved.last_active
                    )
                )
                if len(sessions) == 51:
                    break
        return ListSessionsResponse(
            sessions=sessions[:50],
            next_cursor=sessions[49].session_id if len(sessions) > 50 else None,
        )

    async def prompt(
        self, session_id: str, prompt: list[Any], **kwargs: Any
    ) -> PromptResponse:
        session = self.sessions.get(session_id)
        if session is None:
            raise RequestError.invalid_params({"sessionId": session_id})
        if session.task is not None:
            raise RequestError.invalid_request(
                {"reason": "A turn is already active for this session"}
            )
        assets = None
        if self._registry.available:
            base = self._registry.store.base_path.resolve()
            assets = base / "acp-assets" / session_id
            if not assets.resolve().is_relative_to(base):
                raise RequestError.invalid_params(
                    {"reason": "Invalid attachment storage"}
                )
        message = prepare_prompt(
            prompt, session.cwd, assets, allow_images=self._image_support
        )
        if self._connection is None:
            raise RequestError.internal_error()
        session.task = asyncio.current_task()
        session.cancelled = False
        sent = False
        gate_owned = False

        async def on_chunk(chunk: str, message_type: str = "assistant") -> None:
            nonlocal sent
            if session.cancelled or message_type != "assistant" or not chunk:
                return
            await self._send_update(
                session_id,
                AgentMessageChunk(
                    content=text_block(chunk), session_update="agent_message_chunk"
                ),
            )
            sent = True

        try:
            await self._process_gate.acquire()
            gate_owned = True
            if session.cancelled:
                return PromptResponse(stop_reason="cancelled")
            session.running = True
            for block in prompt:
                self._registry.record(
                    session_id,
                    UserMessageChunk(
                        session_update="user_message_chunk", content=block
                    ),
                )
            with contextlib.ExitStack() as scopes:
                if session.mcp_provider is not None:
                    scopes.enter_context(
                        mcp_provider_scope(self.core.tool_manager, session.mcp_provider)
                    )
                scopes.enter_context(
                    execution_context_scope(
                        ExecutionContext(
                            session_id=session_id,
                            conversation_id=session_id,
                            directory=str(session.cwd),
                            project_root=str(session.cwd),
                            request_id=uuid4().hex,
                        )
                    )
                )
                result = await self.core.process(
                    message,
                    conversation_id=session_id,
                    streaming=True,
                    stream_callback=on_chunk,
                )
            if not isinstance(result, dict):
                raise RequestError.internal_error(
                    {"reason": "Penguin returned no valid turn result"}
                )
            if session.cancelled or result.get("aborted"):
                return PromptResponse(stop_reason="cancelled")
            if result.get("error") or result.get("status") in {
                "error",
                "provider_error",
                "failed",
            }:
                raise RequestError.internal_error(
                    {"reason": "Penguin could not complete the turn"}
                )
            text = result.get("assistant_response") or ""
            if text and not sent:
                await on_chunk(text)
            stop_reason = result.get("stop_reason", "end_turn")
            if stop_reason not in {
                "end_turn",
                "max_tokens",
                "max_turn_requests",
                "refusal",
                "cancelled",
            }:
                raise RequestError.internal_error(
                    {"reason": "Unknown turn stop reason"}
                )
            return PromptResponse(stop_reason=stop_reason)
        except asyncio.CancelledError:
            session.cancelled = True
            return PromptResponse(stop_reason="cancelled")
        except RequestError:
            raise
        except Exception:
            logger.exception("ACP turn failed")
            raise RequestError.internal_error(
                {"reason": "Penguin could not complete the turn"}
            ) from None
        finally:
            try:
                await self._events.end_turn(session_id)
            finally:
                try:
                    if gate_owned:
                        self._registry.checkpoint(session_id)
                finally:
                    if session.cancelled:
                        for request in self._approvals.get_pending(session_id):
                            self._approvals.deny(request.id)
                    session.running = False
                    session.task = None
                    if gate_owned:
                        self._process_gate.release()

    async def cancel(self, session_id: str, **kwargs: Any) -> None:
        session = self.sessions.get(session_id)
        if session is None or session.task is None:
            return
        session.cancelled = True
        for request in self._approvals.get_pending(session_id):
            self._approvals.deny(request.id)
        # A queued turn has no Penguin execution to abort. Cancel it without
        # interrupting the other session that currently owns the process gate.
        task = session.task
        try:
            if session.running:
                await self.core.abort_session(session_id)
        finally:
            task.cancel()

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
                        PermissionOption(
                            option_id="allow_once", name="Allow once", kind="allow_once"
                        ),
                        PermissionOption(
                            option_id="reject_once", name="Reject", kind="reject_once"
                        ),
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

    from penguin.integrations.acp.stdio import protocol_writer

    output = sys.stdout.buffer
    # The SDK's Windows writer resolves sys.stdout on each write, so capturing
    # its streams alone does not protect stdout when diagnostics are redirected.
    with contextlib.redirect_stdout(sys.stderr):
        from penguin.config import WORKSPACE_PATH
        from penguin.core import PenguinCore

        core = await PenguinCore.create(show_progress=False)
        reader, _ = await stdio_streams(limit=50 * 1024 * 1024)
        writer = protocol_writer(output)
        roots = (Path.cwd(), Path(WORKSPACE_PATH))
        agent = PenguinACPAgent(core, allowed_roots=roots)
        try:
            # SDK 0.12 calls resume/close "unstable" although current v1 docs
            # include them. Unimplemented draft methods still return not found.
            await run_agent(
                agent,
                input_stream=writer,
                output_stream=reader,
                use_unstable_protocol=True,
            )
        finally:
            agent.close()


def main() -> int:
    logging.basicConfig(stream=sys.stderr)
    asyncio.run(serve())
    return 0
