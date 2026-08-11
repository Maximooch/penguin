"""In-memory channel adapter used by transport contract tests."""

from __future__ import annotations

import asyncio
from typing import Any

from penguin.channels.chat import ChatProcessRequest, execute_chat_turn
from penguin.channels.schema import DeliveryRequest, StreamUpdate

__all__ = ["FakeChannel"]


class FakeChannel:
    """Capture streams and deliveries without I/O."""

    def __init__(self) -> None:
        self.streams: list[StreamUpdate] = []
        self.deliveries: list[DeliveryRequest] = []
        self._active: set[asyncio.Task[Any]] = set()

    async def execute(self, core: Any, request: ChatProcessRequest) -> dict[str, Any]:
        """Execute and capture stream deltas through the public chat seam."""

        outer_callback = request.stream_callback

        async def capture(text: str, kind: str = "assistant") -> None:
            self.streams.append(StreamUpdate(text=text, kind=kind))
            if outer_callback is not None:
                await outer_callback(text, kind)

        captured_request = ChatProcessRequest(
            input_data=request.input_data,
            execution_context=request.execution_context,
            session_id=request.session_id,
            context=request.context,
            agent_id=request.agent_id,
            max_iterations=request.max_iterations,
            context_files=request.context_files,
            streaming=request.streaming,
            stream_callback=capture,
            api_client_override=request.api_client_override,
            model_config_override=request.model_config_override,
        )
        task = asyncio.current_task()
        if task is not None:
            self._active.add(task)
        try:
            result = await execute_chat_turn(core, captured_request)
            self.streams.append(
                StreamUpdate(
                    text=str(result.get("assistant_response") or ""),
                    final=True,
                )
            )
            return result
        finally:
            if task is not None:
                self._active.discard(task)

    def cancel_all(self) -> int:
        """Cancel every active fake transport request."""

        tasks = tuple(self._active)
        for task in tasks:
            task.cancel()
        return len(tasks)

    async def deliver(self, request: DeliveryRequest) -> None:
        self.deliveries.append(request)
