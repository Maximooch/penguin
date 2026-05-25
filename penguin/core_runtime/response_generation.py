"""Response generation helpers for :mod:`penguin.core`."""

from __future__ import annotations

import asyncio
import json
from typing import Any

__all__ = ["get_response"]


async def _fetch_assistant_response(
    owner: Any,
    messages: list[dict[str, Any]],
    *,
    streaming: bool | None,
    stream_callback: Any,
    sleep: Any,
    log: Any,
) -> str | None:
    max_retries = 2
    retry_count = 0

    while retry_count <= max_retries:
        log.debug(
            "Calling API directly (Streaming: %s, Callback provided: %s)",
            streaming,
            stream_callback is not None,
        )

        assistant_response = None
        try:
            log.debug(
                json.dumps(
                    owner.conversation_manager.conversation.get_formatted_messages(),
                    indent=2,
                )
            )
            assistant_response = await owner.api_client.get_response(
                messages=messages,
                stream=streaming,
                stream_callback=stream_callback,
            )
        except asyncio.CancelledError:
            log.warning("APIClient response retrieval was cancelled")
        except Exception as exc:
            log.error(
                "Error during APIClient response retrieval: %s",
                exc,
                exc_info=True,
            )

        if assistant_response and assistant_response.strip():
            return assistant_response

        retry_count += 1
        if retry_count <= max_retries:
            log.warning(
                "Empty response from API (attempt %s/%s), retrying...",
                retry_count,
                max_retries,
            )
            await sleep(1 * retry_count)
            continue

        log.warning("Empty response from API after %s attempts", max_retries)
        return (
            "I apologize, but I encountered an issue generating a response. "
            "Please try again."
        )

    return None


async def get_response(
    owner: Any,
    *,
    current_iteration: int | None,
    max_iterations: int | None,
    stream_callback: Any,
    streaming: bool | None,
    process_response_actions: Any,
    sleep: Any,
    log_error: Any,
    log: Any,
) -> tuple[dict[str, Any], bool]:
    """Generate one assistant response and execute any parsed actions."""
    try:
        if current_iteration is not None and max_iterations is not None:
            owner.conversation_manager.conversation.add_iteration_marker(
                current_iteration,
                max_iterations,
            )

        messages = owner.conversation_manager.conversation.get_formatted_messages()
        assistant_response = await _fetch_assistant_response(
            owner,
            messages,
            streaming=streaming,
            stream_callback=stream_callback,
            sleep=sleep,
            log=log,
        )

        log.debug(
            "[Core.get_response] Processing response and executing actions. "
            "Streaming=%s",
            streaming,
        )

        if assistant_response:
            owner.conversation_manager.conversation.add_assistant_message(
                assistant_response
            )

        action_processing = await process_response_actions(
            owner,
            assistant_response,
            log=log,
        )

        owner.conversation_manager.save()

        full_response = {
            "assistant_response": assistant_response,
            "actions": action_processing.actions,
            "action_results": action_processing.action_results,
            "metadata": {
                "iteration": current_iteration,
                "max_iterations": max_iterations,
            },
        }

        log.debug(
            "ACTION RESULT TEST: System outputs visible to LLM: %s",
            [
                msg
                for msg in messages
                if "system" in msg.get("role", "")
                and "Action executed" in str(msg.get("content", ""))
            ],
        )

        return full_response, action_processing.exit_continuation

    except Exception as exc:
        log_error(
            exc,
            context={
                "component": "core",
                "method": "get_response",
                "iteration": current_iteration,
                "max_iterations": max_iterations,
            },
        )
        return {
            "assistant_response": f"I apologize, but an error occurred: {exc!s}",
            "action_results": [],
        }, False
