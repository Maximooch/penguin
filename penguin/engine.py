from __future__ import annotations

"""Engine – high‑level coordination layer for Penguin.

The Engine owns the reasoning loop (single‑turn and multi‑step), delegates
LLM calls to ``APIClient`` and tool execution to ``ActionExecutor``, and
maintains light run‑time state (start‑time, iteration counter, active
stop‑conditions).  It receives pre‑constructed managers from PenguinCore so it
remains test‑friendly and avoids hidden globals.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
import asyncio
import multiprocessing as mp
from typing import Any, Callable, Coroutine, List, Optional, Sequence

from penguin.system.conversation_manager import ConversationManager  # type: ignore
from penguin.utils.parser import parse_action, CodeActAction, ActionExecutor  # type: ignore
from penguin.system.state import MessageCategory  # type: ignore
from penguin.llm.api_client import APIClient  # type: ignore
from penguin.tools import ToolManager  # type: ignore
import logging

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Settings & Stop‑conditions
# ---------------------------------------------------------------------------

@dataclass
class EngineSettings:
    """Immutable configuration for an Engine instance."""

    retry_attempts: int = 2
    backoff_seconds: float = 1.5
    streaming_default: bool = False
    max_iterations_default: int = 5
    token_budget_stop_enabled: bool = False
    wall_clock_stop_seconds: Optional[int] = None


class StopCondition:
    """Base class for pluggable stop conditions."""

    async def should_stop(self, engine: "Engine") -> bool:  # noqa: F821
        raise NotImplementedError


class TokenBudgetStop(StopCondition):
    async def should_stop(self, engine: "Engine") -> bool:
        cw = engine.conversation_manager.context_window
        return cw.is_over_budget() if cw else False


class WallClockStop(StopCondition):
    def __init__(self, max_seconds: int):
        self.max_delta = timedelta(seconds=max_seconds)

    async def should_stop(self, engine: "Engine") -> bool:
        return datetime.utcnow() - engine.start_time >= self.max_delta


class ExternalCallbackStop(StopCondition):
    def __init__(self, coro: Callable[["Engine"], Coroutine[Any, Any, bool]]):
        self.coro = coro

    async def should_stop(self, engine: "Engine") -> bool:
        return await self.coro(engine)


# ---------------------------------------------------------------------------
# Engine core
# ---------------------------------------------------------------------------

class Engine:
    """High‑level coordinator for reasoning / action loops."""

    def __init__(
        self,
        settings: EngineSettings,
        conversation_manager: ConversationManager,
        api_client: APIClient,
        tool_manager: ToolManager,
        action_executor: ActionExecutor,
        *,
        stop_conditions: Optional[Sequence[StopCondition]] = None,
    ) -> None:
        self.settings = settings
        self.conversation_manager = conversation_manager
        self.api_client = api_client
        self.tool_manager = tool_manager
        self.action_executor = action_executor
        self.stop_conditions: List[StopCondition] = list(stop_conditions or [])

        # Inject default conditions based on settings
        if settings.token_budget_stop_enabled and not any(isinstance(s, TokenBudgetStop) for s in self.stop_conditions):
            self.stop_conditions.append(TokenBudgetStop())
        if settings.wall_clock_stop_seconds and not any(isinstance(s, WallClockStop) for s in self.stop_conditions):
            self.stop_conditions.append(WallClockStop(settings.wall_clock_stop_seconds))

        # Light run‑time state
        self.start_time: datetime = datetime.utcnow()
        self.current_iteration: int = 0
        self._interrupted: bool = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run_single_turn(self, prompt: str, *, tools_enabled: bool = True, streaming: Optional[bool] = None):
        """Run a single reasoning → (optional) action → response cycle.

        Returns the same structured dict that ``_llm_step`` emits so callers
        may access both the assistant text **and** any action_results.
        """
        self.conversation_manager.conversation.prepare_conversation(prompt)
        response_data = await self._llm_step(tools_enabled=tools_enabled, streaming=streaming)
        return response_data

    async def stream(self, prompt: str):
        """Yield chunks as they arrive (if provider supports streaming)."""
        async for chunk in self._llm_stream(prompt):
            yield chunk

    async def run_task(self, task_prompt: str, max_iterations: Optional[int] = None) -> str:
        """Multi‑step loop – exits on stop‑condition or completion phrase."""
        max_iters = max_iterations or self.settings.max_iterations_default
        self.current_iteration = 0
        self.start_time = datetime.utcnow()
        self.conversation_manager.conversation.prepare_conversation(task_prompt) # Does run_task start a new conversation, or go off the existing one? Can this be configured?

        last_response = ""
        while self.current_iteration < max_iters:
            self.current_iteration += 1
            logger.debug("Engine iteration %s", self.current_iteration)

            response_data = await self._llm_step()
            last_response = response_data.get("assistant_response", "")

            if await self._check_stop():
                break
        return last_response

    # ------------------------------------------------------------------
    # Child‑engine spawning (stub – process mode)
    # ------------------------------------------------------------------

    async def spawn_child(self, *, purpose: str = "child", inherit_tools: bool = False, shared_conversation: bool = False) -> "Engine":
        """Spawn a sub‑engine in a separate process.  Minimal stub for now."""
        logger.warning("spawn_child is a stub – running in‑process for now")
        cm = self.conversation_manager if shared_conversation else ConversationManager(
            model_config=self.conversation_manager.model_config,
            api_client=self.api_client,
            workspace_path=self.conversation_manager.workspace_path,
            system_prompt=self.conversation_manager.conversation.system_prompt,
        )
        tm = self.tool_manager if inherit_tools else ToolManager(self.tool_manager.error_handler)
        ae = ActionExecutor(tm, self.action_executor.task_manager, cm.conversation)
        return Engine(self.settings, cm, self.api_client, tm, ae, stop_conditions=self.stop_conditions)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _llm_step(self, *, tools_enabled: bool = True, streaming: Optional[bool] = None):
        messages = self.conversation_manager.conversation.get_formatted_messages()
        assistant_response = await self.api_client.get_response(messages, stream=streaming)

        # Add assistant message to conversation
        self.conversation_manager.conversation.add_assistant_message(assistant_response)

        action_results = []
        if tools_enabled:
            actions: List[CodeActAction] = parse_action(assistant_response)
            for act in actions:
                result = await self.action_executor.execute_action(act)
                action_results.append(result)
                # Persist result
                self.conversation_manager.add_action_result(act.action_type.value, str(result))

        # Persist conversation state
        self.conversation_manager.save()
        return {"assistant_response": assistant_response, "action_results": action_results}

    async def _llm_stream(self, prompt: str):
        """Helper to stream chunks to caller."""
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[str] = asyncio.Queue()

        async def run():
            # Prepare conversation
            self.conversation_manager.conversation.prepare_conversation(prompt)

            # Inner callback forwards chunks into queue
            async def _cb(chunk: str):
                await queue.put(chunk)

            # Call provider with streaming enabled
            messages = self.conversation_manager.conversation.get_formatted_messages()
            full_response = await self.api_client.get_response(
                messages,
                stream=True,
                stream_callback=lambda c: asyncio.create_task(_cb(c)),
            )

            # Persist full assistant response now that streaming done
            self.conversation_manager.conversation.add_assistant_message(full_response)
            self.conversation_manager.save()

            await queue.put(None)  # sentinel

        loop.create_task(run())
        while True:
            chunk = await queue.get()
            if chunk is None:
                break
            yield chunk

    async def _check_stop(self) -> bool:
        for cond in self.stop_conditions:
            if await cond.should_stop(self):
                logger.info("Engine stopping due to %s", cond.__class__.__name__)
                return True
        return False
