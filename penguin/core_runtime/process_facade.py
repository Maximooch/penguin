"""Message processing compatibility facade methods for ``PenguinCore``."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from penguin.utils.log_error import log_error

from . import (
    action_execution as core_action_execution,
    conversations as core_conversations,
    message_processing as core_message_processing,
    process_runtime as core_process_runtime,
    response_generation as core_response_generation,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from penguin.llm.api_client import APIClient
    from penguin.llm.model_config import ModelConfig

__all__ = ["ProcessCoreFacade"]

logger = logging.getLogger("penguin.core")


def _trace_log_info(message: str, *args: Any) -> None:
    """Mirror process trace logs to uvicorn for live server debugging."""
    logger.info(message, *args)
    uvicorn_logger = logging.getLogger("uvicorn.error")
    if uvicorn_logger is not logger:
        uvicorn_logger.info(message, *args)


class ProcessCoreFacade:
    """Compatibility methods for public message processing APIs."""

    def _check_interrupt(self) -> bool:
        """Check if execution has been interrupted."""
        return self._interrupted

    async def process_message(
        self,
        message: str,
        context: dict[str, Any] | None = None,
        conversation_id: str | None = None,
        agent_id: str | None = None,
        context_files: list[str] | None = None,
        streaming: bool = False,
    ) -> str:
        """Process a message with optional conversation support."""
        return await core_message_processing.process_message(
            self,
            message=message,
            context=context,
            conversation_id=conversation_id,
            agent_id=agent_id,
            context_files=context_files,
            streaming=streaming,
            resolve_conversation_manager=(
                core_conversations.resolve_conversation_manager
            ),
            log_error=log_error,
            log=logger,
        )

    async def get_response(
        self,
        current_iteration: int | None = None,
        max_iterations: int | None = None,
        stream_callback: Callable[[str], None] | None = None,
        streaming: bool | None = None,
    ) -> tuple[dict[str, Any], bool]:
        """Generate a response using conversation context and execute actions."""
        return await core_response_generation.get_response(
            self,
            current_iteration=current_iteration,
            max_iterations=max_iterations,
            stream_callback=stream_callback,
            streaming=streaming,
            process_response_actions=core_action_execution.process_response_actions,
            sleep=asyncio.sleep,
            log_error=log_error,
            log=logger,
        )

    async def execute_action(self, action: Any) -> dict[str, Any]:
        """Execute an action and return a structured result."""
        return await core_action_execution.execute_action(self, action)

    async def process(
        self,
        input_data: dict[str, Any] | str,
        context: dict[str, Any] | None = None,
        conversation_id: str | None = None,
        agent_id: str | None = None,
        max_iterations: int | None = None,
        context_files: list[str] | None = None,
        streaming: bool | None = None,
        stream_callback: Callable[[str], None] | None = None,
        multi_step: bool = True,
        api_client_override: APIClient | None = None,
        model_config_override: ModelConfig | None = None,
    ) -> dict[str, Any]:
        """Process a message through Penguin."""
        return await core_process_runtime.process_with_retry(
            self,
            input_data=input_data,
            context=context,
            conversation_id=conversation_id,
            agent_id=agent_id,
            max_iterations=max_iterations,
            context_files=context_files,
            streaming=streaming,
            stream_callback=stream_callback,
            multi_step=multi_step,
            api_client_override=api_client_override,
            model_config_override=model_config_override,
            log=logger,
            trace_log_info=_trace_log_info,
            log_error_fn=log_error,
        )
