"""A2A v1 transport for Penguin's existing chat execution engine."""

from __future__ import annotations

import asyncio
import logging
import os
import secrets
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse
from uuid import uuid4

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.routes import (
    create_agent_card_routes,
    create_rest_routes,
)
from a2a.server.tasks.database_task_store import DatabaseTaskStore
from a2a.server.tasks.task_updater import TaskUpdater
from a2a.types import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    AgentSkill,
    Artifact,
    HTTPAuthSecurityScheme,
    Message,
    Part,
    Role,
    SecurityRequirement,
    SecurityScheme,
    StringList,
    Task,
    TaskState,
    TaskStatus,
)
from google.protobuf.json_format import MessageToDict
from sqlalchemy.ext.asyncio import create_async_engine

from penguin import __version__
from penguin.web.services.chat_requests import ChatRequestStore, execute_chat_request
from penguin.web.services.link_inference import LinkExecutionRequest

if TYPE_CHECKING:
    from a2a.server.events.event_queue import EventQueue
    from fastapi import FastAPI

__all__ = ["add_penguin_a2a_routes"]

logger = logging.getLogger(__name__)


def _workspace(core: Any) -> Path:
    from penguin.config import WORKSPACE_PATH

    path = Path(
        getattr(getattr(core, "config", None), "workspace_path", None) or WORKSPACE_PATH
    )
    path.mkdir(parents=True, exist_ok=True)
    return path


class ReceiptTaskStore(DatabaseTaskStore):
    """Repair an A2A task from Penguin's durable execution receipt on lookup."""

    def __init__(
        self, *args: Any, request_store: ChatRequestStore, **kwargs: Any
    ) -> None:
        super().__init__(*args, **kwargs)
        self.request_store = request_store

    async def get(self, task_id: str, context: Any) -> Task | None:
        task = await super().get(task_id, context)
        if (
            not task
            or not task.history
            or task.status.state
            in {
                TaskState.TASK_STATE_COMPLETED,
                TaskState.TASK_STATE_CANCELED,
                TaskState.TASK_STATE_FAILED,
                TaskState.TASK_STATE_REJECTED,
            }
        ):
            return task
        receipt = await asyncio.to_thread(
            self.request_store.lookup, task.context_id, task.history[0].message_id
        )
        if receipt.get("state") != "completed":
            return task
        if receipt.get("http_error"):
            task.status.state = TaskState.TASK_STATE_FAILED
            await super().save(task, context)
            return task
        response = receipt.get("response")
        if not isinstance(response, dict):
            return task
        if response.get("aborted") is True and response.get("status") == "stopped":
            task.status.state = TaskState.TASK_STATE_CANCELED
        elif (
            isinstance(response.get("response"), str)
            and not response.get("error")
            and not response.get("recoverable")
            and response.get("status") not in {"recovering", "accepted", "working"}
        ):
            if not task.artifacts:
                task.artifacts.append(
                    Artifact(
                        artifact_id=f"response:{task.id}",
                        name="response",
                        parts=[Part(text=response["response"])],
                    )
                )
            if not task.status.message:
                task.status.message = Message(
                    message_id=f"response:{task.id}",
                    role=Role.ROLE_AGENT,
                    parts=[Part(text=response["response"])],
                    task_id=task.id,
                    context_id=task.context_id,
                )
            task.status.state = TaskState.TASK_STATE_COMPLETED
        else:
            return task
        await super().save(task, context)
        return task


class PenguinA2AExecutor(AgentExecutor):
    """Map one A2A task to one durable Penguin chat request."""

    def __init__(self, core: Any, request_store: ChatRequestStore) -> None:
        self.core = core
        self.request_store = request_store

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        message = context.message
        task_id = context.task_id
        context_id = context.context_id
        if not message or not task_id or not context_id:
            raise ValueError("A2A task requires message, task ID, and context ID.")

        await event_queue.enqueue_event(
            Task(
                id=task_id,
                context_id=context_id,
                status=TaskStatus(state=TaskState.TASK_STATE_SUBMITTED),
                history=[message],
            )
        )
        updater = TaskUpdater(
            event_queue=event_queue, task_id=task_id, context_id=context_id
        )
        await updater.start_work()

        authority_message = message
        if context.current_task and context.current_task.history:
            authority_message = context.current_task.history[0]
        metadata = (
            MessageToDict(authority_message.metadata)
            if authority_message.HasField("metadata")
            else {}
        )
        link_execution_data = metadata.get("link_execution")
        link_execution = None
        if link_execution_data is not None:
            headers = context.call_context.state.get("headers", {})
            token = (
                headers.get("x-link-execution-key", "")
                if isinstance(headers, dict)
                else ""
            )
            expected = os.getenv("LINK_API_KEY", "").strip()
            if not expected or not secrets.compare_digest(token, expected):
                await updater.failed()
                return
            try:
                link_execution = LinkExecutionRequest.model_validate(
                    link_execution_data
                )
            except Exception:
                await updater.failed()
                return

        # Import here so the existing route module can finish loading first.
        from penguin.web.routes import MessageRequest, _process_chat_message

        request = MessageRequest(
            text=context.get_user_input(),
            session_id=context_id,
            conversation_id=context_id,
            client_message_id=message.message_id,
            streaming=False,
            link_execution=link_execution,
            model=link_execution.requested_model_id if link_execution else None,
        )
        try:
            response = await execute_chat_request(
                lambda: self.request_store,
                context_id,
                message.message_id,
                {"text": request.text, "context_id": context_id},
                lambda: _process_chat_message(request, self.core),
            )
        except Exception:
            receipt = await asyncio.to_thread(
                self.request_store.lookup, context_id, message.message_id
            )
            if receipt.get("state") == "completed" and receipt.get("http_error"):
                await updater.failed()
                return
            logger.exception("A2A task %s lost its Penguin execution receipt", task_id)
            # Unknown execution state stays nonterminal.
            return

        if response.get("aborted") is True and response.get("status") == "stopped":
            await updater.cancel()
            return
        if response.get("status") in {
            "recovering",
            "accepted",
            "working",
        } or response.get("recoverable"):
            return
        if response.get("status") in {"error", "provider_error"}:
            await updater.failed()
            return
        if response.get("error"):
            # Provider errors can follow accepted side effects. Keep the task
            # open until a durable receipt can be reconciled.
            return
        answer = response.get("response")
        if not isinstance(answer, str):
            return
        await updater.add_artifact(
            parts=[Part(text=answer)], name="response", last_chunk=True
        )
        await updater.complete(
            Message(
                message_id=str(uuid4()),
                role=Role.ROLE_AGENT,
                parts=[Part(text=answer)],
                task_id=task_id,
                context_id=context_id,
            )
        )

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        task = context.current_task
        context_id = context.context_id
        task_id = context.task_id
        if not task or not task.history or not context_id or not task_id:
            raise ValueError("A2A task has no durable request identity.")
        request_id = task.history[0].message_id
        receipt = await asyncio.to_thread(
            self.request_store.cancel, context_id, request_id
        )
        if (
            receipt.get("state") == "completed"
            and receipt.get("response", {}).get("aborted") is True
        ):
            await TaskUpdater(
                event_queue=event_queue, task_id=task_id, context_id=context_id
            ).cancel()
        # Accepted work remains working until its execution owner confirms Stop.


def add_penguin_a2a_routes(app: FastAPI, core: Any) -> bool:
    """Mount an authenticated A2A endpoint when explicitly configured."""
    api_key = os.getenv("PENGUIN_A2A_API_KEY", "").strip()
    base_url = os.getenv("PENGUIN_A2A_BASE_URL", "").strip().rstrip("/")
    if not api_key or not base_url:
        return False
    parsed = urlparse(base_url)
    if parsed.scheme != "https" and not (
        parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", "::1"}
    ):
        raise ValueError("PENGUIN_A2A_BASE_URL must use HTTPS outside loopback.")
    if (
        parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise ValueError(
            "PENGUIN_A2A_BASE_URL must be an origin without credentials or query data."
        )

    workspace = _workspace(core)
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{workspace / 'a2a-tasks.sqlite3'}"
    )
    card = AgentCard(
        name="Penguin",
        description="Penguin software and research agent",
        version=__version__,
        capabilities=AgentCapabilities(streaming=True),
        security_schemes={
            "bearer": SecurityScheme(
                http_auth_security_scheme=HTTPAuthSecurityScheme(scheme="Bearer")
            )
        },
        security_requirements=[SecurityRequirement(schemes={"bearer": StringList()})],
        default_input_modes=["text/plain"],
        default_output_modes=["text/plain"],
        skills=[
            AgentSkill(
                id="penguin",
                name="Penguin",
                description="Use Penguin tools to complete tasks.",
                tags=["code", "research"],
            )
        ],
        supported_interfaces=[
            AgentInterface(
                protocol_binding="HTTP+JSON",
                protocol_version="1.0",
                url=f"{base_url}/a2a/rest",
            )
        ],
    )
    request_store = ChatRequestStore(workspace / "a2a-chat-requests.sqlite3")
    handler = DefaultRequestHandler(
        agent_executor=PenguinA2AExecutor(core, request_store),
        task_store=ReceiptTaskStore(engine, request_store=request_store),
        agent_card=card,
    )
    app.router.routes.extend(create_agent_card_routes(card))
    app.router.routes.extend(create_rest_routes(handler, path_prefix="/a2a/rest"))
    return True
