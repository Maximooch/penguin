"""Negotiated form questions with a nonblocking text fallback."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from acp.helpers import text_block
from acp.schema import AgentMessageChunk, ElicitationFormSessionMode, ElicitationSchema

from penguin.security.question import QuestionStatus, get_question_manager

if TYPE_CHECKING:
    from penguin.security.question import QuestionRequest


class QuestionBridge:
    def __init__(self, owner: Any) -> None:
        self.owner = owner
        self.manager = get_question_manager()
        self.supported = False
        self.tasks: dict[str, set[asyncio.Task[Any]]] = {}
        self.callback = self.on_request
        self.manager.on_request_created(self.callback)

    def cancel(self, sid: str) -> None:
        for request in self.manager.list_pending(sid):
            self.manager.reject(request.id)
        for task in self.tasks.get(sid, set()).copy():
            task.cancel()

    def close(self) -> None:
        if self.callback in self.manager._on_request_created:
            self.manager._on_request_created.remove(self.callback)
        for sid in self.tasks:
            self.cancel(sid)

    def on_request(self, request: QuestionRequest) -> None:
        sid = request.session_id
        session = self.owner.sessions.get(sid)
        child = self.owner._children.children.get(sid)
        if session is None and child is None:
            return
        if (
            self.owner._closed
            or (session and session.cancelled)
            or (child and (not child.active or child.cancelled))
        ):
            self.manager.reject(request.id)
            return
        loop = self.owner._loop
        if loop is None:
            self.manager.reject(request.id)
            return

        def schedule() -> None:
            if self.owner._closed or request.status != QuestionStatus.PENDING:
                self.manager.reject(request.id)
                return
            task = loop.create_task(self.ask(request))
            owned = self.tasks.setdefault(sid, set())
            owned.add(task)
            task.add_done_callback(owned.discard)

        loop.call_soon_threadsafe(schedule)

    async def fallback(self, request: QuestionRequest) -> None:
        text = "Please answer in your next message:\n" + "\n".join(
            str(q.get("question", ""))[:4096]
            + " Choices: "
            + ", ".join(
                str(o.get("label", ""))[:256] for o in q.get("options", [])[:20]
            )
            for q in request.questions[:10]
        )
        await self.owner._send_update(
            request.session_id,
            AgentMessageChunk(
                session_update="agent_message_chunk", content=text_block(text)
            ),
        )

    async def ask(self, request: QuestionRequest) -> None:
        try:
            if not self.supported:
                await self.fallback(request)
                return
            properties = {}
            if not 1 <= len(request.questions) <= 10:
                raise ValueError("Too many questions")
            for i, question in enumerate(request.questions):
                labels = [str(o["label"]) for o in question["options"]]
                if not labels or len(labels) > 20 or any(len(v) > 4096 for v in labels):
                    raise ValueError("Invalid choices")
                field = {
                    "title": str(question["header"])[:100],
                    "description": str(question["question"])[:4096],
                }
                if question.get("multiple"):
                    if question.get("custom", True):
                        raise ValueError("Custom multi-select requires a text reply")
                    field.update(
                        type="array",
                        items={"type": "string", "enum": labels},
                        minItems=1,
                        maxItems=len(labels),
                    )
                else:
                    field.update(type="string", minLength=1, maxLength=4096)
                    if not question.get("custom", True):
                        field["enum"] = labels
                    else:
                        field["description"] += " Choices: " + ", ".join(labels)
                properties[str(i)] = field
            child = self.owner._children.children.get(request.session_id)
            target = (
                child.root
                if child and not self.owner._children.native
                else request.session_id
            )
            await self.owner._update_child_approval_state(request.session_id)
            response = await asyncio.wait_for(
                self.owner._connection.create_elicitation(
                    "Penguin needs your input",
                    ElicitationFormSessionMode(
                        session_id=target,
                        requested_schema=ElicitationSchema.model_validate(
                            {
                                "properties": properties,
                                "required": list(properties),
                            }
                        ),
                    ),
                ),
                300,
            )
            if response.action != "accept" or request.status != QuestionStatus.PENDING:
                return
            content = response.content or {}
            answers = []
            for i, question in enumerate(request.questions):
                value = content.get(str(i))
                values = value if question.get("multiple") else [value]
                labels = [o["label"] for o in question["options"]]
                if (
                    not isinstance(values, list)
                    or not values
                    or any(
                        not isinstance(v, str)
                        or not v
                        or len(v) > 4096
                        or (not question.get("custom", True) and v not in labels)
                        for v in values
                    )
                ):
                    raise ValueError("Invalid answer")
                answers.append(values)
            self.manager.reply(request.id, answers)
        except asyncio.CancelledError:
            raise
        except Exception:
            if request.status == QuestionStatus.PENDING and not self.owner._closed:
                await self.fallback(request)
        finally:
            if request.status == QuestionStatus.PENDING:
                self.manager.reject(request.id)
            await self.owner._update_child_approval_state(request.session_id)
