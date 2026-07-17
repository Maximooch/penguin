import glob
import html
import json
import logging
import os
import time
import uuid
import yaml  # type: ignore
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from penguin.config import CONVERSATION_CONFIG
from penguin.system.native_tool_history import (
    sanitize_native_tool_messages,
    sanitize_native_tool_session,
)
from penguin.system.runtime_diagnostics import record_runtime_duration
from penguin.system.state import Message, MessageCategory, Session
from penguin.utils.diagnostics import diagnostics

try:
    from penguin.system.message_bus import MessageBus, ProtocolMessage
except Exception:  # pragma: no cover - optional import to avoid cycles in minimal envs
    MessageBus = None  # type: ignore
    ProtocolMessage = None  # type: ignore

# Optional - can be replaced with approximation method for multiple providers
try:
    import tiktoken  # type: ignore

    TOKENIZER_AVAILABLE = True
except ImportError:
    TOKENIZER_AVAILABLE = False

logger = logging.getLogger(__name__)


def is_human_visible_message(message: Message) -> bool:
    """Return whether a persisted message may be shown outside model context."""

    category = getattr(message, "category", None)
    category_name = getattr(category, "name", category)
    if category is MessageCategory.INTERNAL or (
        isinstance(category_name, str) and category_name.lower() == "internal"
    ):
        return False

    metadata = getattr(message, "metadata", None)
    visibility = metadata.get("visibility") if isinstance(metadata, dict) else None
    return not (
        isinstance(visibility, str) and visibility.strip().lower() == "internal"
    )


class ConversationSystem:
    """
    Manages conversation state and message preparation.

    Handles message categorization, history management, and API formatting.
    Uses external systems for token budgeting and context management.
    """

    def __init__(
        self,
        context_window_manager=None,
        session_manager=None,
        system_prompt: str = "",
        checkpoint_manager=None,
    ):
        """
        Initialize the conversation system.

        Args:
            context_window_manager: Manager for token budgeting and context trimming
            session_manager: Manager for session persistence and boundaries
            system_prompt: Initial system prompt
            checkpoint_manager: Manager for conversation checkpointing (optional)
        """
        self.context_window = context_window_manager
        self.session_manager = session_manager
        self.checkpoint_manager = checkpoint_manager
        self.system_prompt = system_prompt
        self.system_prompt_sent = False

        # Create or load initial session
        if session_manager and session_manager.current_session:
            self.session = session_manager.current_session
        else:
            # BUGFIX: Use session_manager.create_session() to ensure the session
            # is added to the sessions cache. Previously, Session() was created
            # directly which bypassed the cache, causing mark_session_modified()
            # to silently fail and preventing auto-save from working.
            if session_manager:
                self.session = session_manager.create_session()
            else:
                # Fallback if no session_manager (testing/isolated usage)
                self.session = Session()

        # Track if save is needed
        self._modified = False
        self._message_bus_tasks: set[Any] = set()

    def set_system_prompt(self, prompt: str) -> None:
        """Set system prompt and mark for sending on next interaction."""
        self.system_prompt = prompt
        self.system_prompt_sent = False

    def _mark_session_modified(self) -> None:
        """Mark the active session dirty in both conversation and cache state."""

        self._modified = True
        if self.session_manager and self.session:
            try:
                self.session_manager.mark_session_modified(self.session.id)
            except Exception:
                logger.warning(
                    "Failed to mark session modified during message append: session=%s",
                    getattr(self.session, "id", "unknown"),
                    exc_info=True,
                )

    def _publish_protocol_message(self, message: Message) -> None:
        """Publish one appended message without making conversation writes block."""

        try:
            metadata = message.metadata if isinstance(message.metadata, dict) else {}
            is_internal_message = (
                message.category is MessageCategory.INTERNAL
                or metadata.get("visibility") == "internal"
            )
            if MessageBus and ProtocolMessage and not is_internal_message:
                bus = MessageBus.get_instance()
                protocol_message = ProtocolMessage(
                    sender=message.agent_id,
                    recipient=None,
                    content=message.content,
                    message_type=message.message_type,
                    metadata={
                        **(message.metadata or {}),
                        "category": message.category.name,
                        "role": message.role,
                    },
                    session_id=self.session.id,
                    message_id=message.id,
                )
                import asyncio as _asyncio

                try:
                    loop = _asyncio.get_running_loop()
                except RuntimeError:
                    return
                task = loop.create_task(bus.send(protocol_message))
                self._message_bus_tasks.add(task)
                task.add_done_callback(self._message_bus_tasks.discard)
        except Exception:
            logger.debug("Failed to publish protocol message", exc_info=True)

    def _schedule_auto_checkpoint(self, message: Message) -> None:
        """Schedule a checkpoint only after its full message unit is appended."""

        if not self.checkpoint_manager or not self.checkpoint_manager.should_checkpoint(
            message
        ):
            return

        import asyncio

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            try:
                asyncio.run(
                    self.checkpoint_manager.create_checkpoint_and_wait(
                        self.session,
                        message,
                    )
                )
            except Exception as exc:
                logger.warning("Failed to create checkpoint: %s", exc)
        else:
            self.checkpoint_manager.schedule_auto_checkpoint(self.session, message)

    def _process_context_window_and_sanitize(self) -> None:
        """Run ordinary CWM processing then fail closed on split native units."""

        if self.context_window:
            self.session = self.context_window.process_session(self.session)
        self.session = sanitize_native_tool_session(self.session)

    def _handle_session_boundary(self) -> None:
        """Advance to a continuation session after a completed append operation."""

        if not self.session_manager or not self.session_manager.check_session_boundary(
            self.session
        ):
            return
        logger.info(
            "Session %s reached boundary, creating continuation", self.session.id
        )
        self.save()
        new_session = self.session_manager.create_continuation_session(self.session)
        self.session = new_session
        self._modified = True
        logger.info("Transitioned to continuation session %s", new_session.id)

    def add_message(
        self,
        role: str,
        content: Any,
        category: MessageCategory = None,
        metadata: Optional[Dict[str, Any]] = None,
        *,
        agent_id: Optional[str] = None,
        recipient_id: Optional[str] = None,
        message_type: str = "message",
    ) -> Message:
        """
        Add a message to the current session.

        Args:
            role: Message role (system, user, assistant)
            content: Message content (string, list, or dict)
            category: Message category for token budgeting
            metadata: Optional metadata for the message

        Returns:
            The created Message object
        """
        # Set default category based on role if not specified
        if category is None:
            if role == "system":
                if content == self.system_prompt:
                    category = MessageCategory.SYSTEM
                elif any(
                    marker in str(content).lower()
                    for marker in [
                        "action executed:",
                        "code saved to:",
                        "result:",
                        "status:",
                    ]
                ):
                    category = MessageCategory.SYSTEM_OUTPUT
                else:
                    category = MessageCategory.CONTEXT
            else:
                category = MessageCategory.DIALOG

        # Resolve agent_id default from session metadata if not provided
        if agent_id is None:
            try:
                agent_id = self.session.metadata.get("agent_id")
            except Exception:
                agent_id = None

        # Create the message
        message = Message(
            role=role,
            content=content,
            category=category,
            id=f"msg_{uuid.uuid4().hex[:8]}",
            timestamp=datetime.now().isoformat(),
            metadata=metadata or {},
            tokens=0,
            agent_id=agent_id,
            recipient_id=recipient_id,
            message_type=message_type,
        )

        # Append one ordinary message.  Native tool replies use the dedicated
        # batch method below so CWM never sees a declaration without its results.
        self.session.add_message(message)
        self._mark_session_modified()
        self._publish_protocol_message(message)
        self._schedule_auto_checkpoint(message)
        self._process_context_window_and_sanitize()
        self._handle_session_boundary()

        return message

    def prepare_conversation(
        self,
        user_input: str,
        image_paths: Optional[List[str]] = None,
        *,
        category: Optional[MessageCategory] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Prepare conversation with user input and optional images.

        Adds system prompt if needed, then adds the user message.

        Args:
            user_input: User message text
            image_paths: Optional list of paths to image files
            category: Optional category for the inserted user message.
            metadata: Optional metadata for the inserted user message.
        """
        # Send system prompt if not sent yet
        if not self.system_prompt_sent and self.system_prompt:
            self.add_message(
                "system",
                self.system_prompt,
                MessageCategory.SYSTEM,
                {"type": "system_prompt"},
                message_type="status",
            )
            self.system_prompt_sent = True

        # Handle image content if provided
        if image_paths:
            # Create multimodal content with text and images
            content: List[Dict[str, Any]] = [{"type": "text", "text": user_input}]
            for path in image_paths:
                content.append({"type": "image_url", "image_path": path})
            self.add_message("user", content, category=category, metadata=metadata)
        else:
            # Simple text content
            self.add_message(
                "user",
                user_input,
                category=category,
                metadata=metadata,
            )

    def add_assistant_message(self, content: str) -> Message:
        """Add a message from the assistant."""
        return self.add_message("assistant", content)

    @staticmethod
    def _native_tool_call_payload(tool_call: Any) -> Optional[Dict[str, str]]:
        """Normalize one runtime tool call into the canonical transcript shape."""

        if isinstance(tool_call, dict):
            call_id = tool_call.get("id") or tool_call.get("call_id")
            name = tool_call.get("name")
            arguments = tool_call.get("arguments")
        else:
            call_id = getattr(tool_call, "id", None)
            name = getattr(tool_call, "name", None)
            arguments = getattr(tool_call, "arguments", None)
        resolved_id = str(call_id or "").strip()
        resolved_name = str(name or "").strip()
        if not resolved_id or not resolved_name:
            return None
        if isinstance(arguments, str):
            resolved_arguments = arguments.strip() or "{}"
        elif arguments is None:
            resolved_arguments = "{}"
        else:
            try:
                resolved_arguments = json.dumps(arguments, sort_keys=True)
            except Exception:
                resolved_arguments = str(arguments)
        return {
            "id": resolved_id,
            "name": resolved_name,
            "arguments": resolved_arguments,
        }

    def _persist_native_tool_runtime_records(
        self,
        tool_calls: List[Dict[str, str]],
        action_results: List[Dict[str, Any]],
    ) -> None:
        """Persist direct-call records without using them as replay evidence."""

        try:
            from penguin.tools.runtime import (
                ToolCall,
                tool_call_record_from_tool_call,
                tool_result_from_action_result,
                tool_result_record_from_tool_result,
            )

            results_by_id = {
                str(result.get("tool_call_id") or "").strip(): result
                for result in action_results
            }
            for tool_call in tool_calls:
                call_id = tool_call["id"]
                self.session.add_tool_call_record(
                    tool_call_record_from_tool_call(
                        ToolCall(
                            id=call_id,
                            name=tool_call["name"],
                            arguments=tool_call["arguments"],
                            source="internal",
                        )
                    )
                )
                action_result = results_by_id[call_id]
                tool_result = tool_result_from_action_result(
                    {
                        "action": tool_call["name"],
                        "result": action_result.get("result", ""),
                        "status": action_result.get("status", "completed"),
                    },
                    call_id=call_id,
                    structured_output={"tool_arguments": tool_call["arguments"]},
                )
                self.session.add_tool_result_record(
                    tool_result_record_from_tool_result(
                        tool_result,
                        arguments=tool_call["arguments"],
                    )
                )
        except Exception as exc:
            logger.warning("Failed to persist tool runtime records: %s", exc)

    def append_native_tool_batch(
        self,
        *,
        tool_calls: List[Any],
        action_results: List[Dict[str, Any]],
        assistant_message_id: Optional[str] = None,
        persist_tool_records: bool = True,
    ) -> List[Message]:
        """Append one complete native tool unit before CWM sees any part of it.

        The optional assistant id is an explicit current-turn handoff from the
        engine.  It is deliberately *not* a search through historic assistant
        messages: if it is not the current tail, a fresh empty assistant
        declaration is created instead.  Empty text is a valid native-tool turn.
        """

        normalized_calls = [
            payload
            for payload in (
                self._native_tool_call_payload(tool_call) for tool_call in tool_calls
            )
            if payload is not None
        ]
        call_ids = [tool_call["id"] for tool_call in normalized_calls]
        results_by_id: Dict[str, Dict[str, Any]] = {}
        for action_result in action_results:
            if not isinstance(action_result, dict):
                continue
            call_id = str(action_result.get("tool_call_id") or "").strip()
            if call_id and call_id not in results_by_id:
                results_by_id[call_id] = dict(action_result)

        # Do not attempt a partial replay.  Native declarations are atomic:
        # duplicate, unknown, or missing ids leave only durable side records.
        if (
            not normalized_calls
            or len(normalized_calls) != len(tool_calls)
            or len(call_ids) != len(set(call_ids))
            or set(results_by_id) != set(call_ids)
            or len(results_by_id) != len(action_results)
        ):
            logger.warning(
                "Dropped incomplete native tool batch: calls=%s result_ids=%s",
                len(normalized_calls),
                sorted(results_by_id),
            )
            return []

        if persist_tool_records:
            self._persist_native_tool_runtime_records(normalized_calls, action_results)

        assistant_message: Optional[Message] = None
        if assistant_message_id and self.session.messages:
            tail = self.session.messages[-1]
            tail_metadata = tail.metadata if isinstance(tail.metadata, dict) else {}
            if (
                tail.role == "assistant"
                and tail.id == assistant_message_id
                and "tool_calls" not in tail_metadata
            ):
                assistant_message = tail

        appended_messages: List[Message] = []
        if assistant_message is None:
            try:
                agent_id = self.session.metadata.get("agent_id")
            except Exception:
                agent_id = None
            assistant_message = Message(
                role="assistant",
                content="",
                category=MessageCategory.DIALOG,
                id=f"msg_{uuid.uuid4().hex[:8]}",
                timestamp=datetime.now().isoformat(),
                metadata={},
                tokens=0,
                agent_id=agent_id,
                message_type="action",
            )
            self.session.add_message(assistant_message)
            appended_messages.append(assistant_message)

        if not isinstance(assistant_message.metadata, dict):
            assistant_message.metadata = {}
        assistant_message.metadata["tool_calls"] = [
            {
                "id": tool_call["id"],
                "type": "function",
                "function": {
                    "name": tool_call["name"],
                    "arguments": tool_call["arguments"],
                },
            }
            for tool_call in normalized_calls
        ]

        tool_messages: List[Message] = []
        for tool_call in normalized_calls:
            action_result = results_by_id[tool_call["id"]]
            tool_message = Message(
                role="tool",
                content=str(action_result.get("result", "")),
                category=MessageCategory.SYSTEM_OUTPUT,
                id=f"msg_{uuid.uuid4().hex[:8]}",
                timestamp=datetime.now().isoformat(),
                metadata={
                    "tool_call_id": tool_call["id"],
                    "action_type": tool_call["name"],
                    "tool_arguments": tool_call["arguments"],
                    "status": action_result.get("status", "completed"),
                },
                tokens=0,
                agent_id=assistant_message.agent_id,
                message_type="action",
            )
            self.session.add_message(tool_message)
            tool_messages.append(tool_message)
            appended_messages.append(tool_message)

        self._mark_session_modified()
        for message in appended_messages:
            self._publish_protocol_message(message)
            self._schedule_auto_checkpoint(message)

        # Run CWM once after the full declaration/results unit is visible, then
        # sanitize the raw canonical order in case category trimming split it.
        self._process_context_window_and_sanitize()
        self._handle_session_boundary()
        return [assistant_message, *tool_messages]

    def add_action_result(
        self,
        action_type: str,
        result: str,
        status: str = "completed",
        *,
        tool_call_id: Optional[str] = None,
        tool_arguments: Optional[str] = None,
    ) -> Message:
        """Append a one-call native tool batch without historic backscanning."""

        resolved_tool_call_id = tool_call_id or f"call_{uuid.uuid4().hex[:8]}"
        assistant_message_id = None
        if self.session.messages:
            tail = self.session.messages[-1]
            tail_metadata = tail.metadata if isinstance(tail.metadata, dict) else {}
            if tail.role == "assistant" and "tool_calls" not in tail_metadata:
                assistant_message_id = tail.id

        appended = self.append_native_tool_batch(
            tool_calls=[
                {
                    "id": resolved_tool_call_id,
                    "name": action_type,
                    "arguments": tool_arguments or "{}",
                }
            ],
            action_results=[
                {
                    "tool_call_id": resolved_tool_call_id,
                    "action": action_type,
                    "result": result,
                    "status": status,
                    "tool_arguments": tool_arguments or "{}",
                }
            ],
            assistant_message_id=assistant_message_id,
        )
        if appended:
            return appended[-1]
        raise RuntimeError("Native tool result could not be appended safely")

    def add_context(self, content: str, source: Optional[str] = None) -> Message:
        """
        Add context information to the conversation.

        Args:
            content: Context content (documentation, files, etc.)
            source: Optional source identifier

        Returns:
            The created Message object
        """
        return self.add_message(
            "system",
            content,
            MessageCategory.CONTEXT,
            {"source": source} if source else {},
        )

    def add_iteration_marker(self, iteration: int, max_iterations: int) -> Message:
        """
        Add an iteration marker for multi-step processing.

        Args:
            iteration: Current iteration number
            max_iterations: Maximum number of iterations

        Returns:
            The created Message object
        """
        content = f"--- Beginning iteration {iteration}/{max_iterations} ---"
        return self.add_message(
            "system",
            content,
            MessageCategory.SYSTEM_OUTPUT,
            {"type": "iteration_marker", "iteration": iteration},
            message_type="status",
        )

    def get_history(self) -> List[Dict[str, Any]]:
        """
        Get formatted conversation history for API consumption.

        Returns:
            List of messages in API-compatible format
        """
        self.session = sanitize_native_tool_session(self.session)
        return self.get_human_history()

    def get_human_history(self) -> List[Dict[str, Any]]:
        """Return API-compatible history without private runtime messages."""

        return [
            {"role": msg.role, "content": msg.content}
            for msg in self.session.messages
            if is_human_visible_message(msg)
        ]

    def get_formatted_messages(self) -> List[Dict[str, Any]]:
        """
        Get formatted messages optimized for API consumption.

        Organizes messages by category priority and formats for the AI model.
        Returns:
            List of formatted message dictionaries
        """
        assembly_started = time.perf_counter()
        # Recovery can load historical pre-fix sessions.  Validate the raw
        # canonical order before projecting it into any provider transcript.
        self.session = sanitize_native_tool_session(self.session)
        # Group by category
        categorized = {
            MessageCategory.SYSTEM: [],
            MessageCategory.CONTEXT: [],
            MessageCategory.DIALOG: [],
            MessageCategory.SYSTEM_OUTPUT: [],
            MessageCategory.INTERNAL: [],
        }

        # Populate categories
        for msg in self.session.messages:
            categorized[msg.category].append(msg)

        # Create ordered list with proper priority
        messages = []

        # System messages first (highest priority)
        messages.extend(
            [
                {"role": msg.role, "content": msg.content}
                for msg in categorized[MessageCategory.SYSTEM]
            ]
        )

        # Context information next
        messages.extend(
            [
                {
                    "role": msg.role,
                    "content": self._format_context_content_for_model(msg),
                }
                for msg in categorized[MessageCategory.CONTEXT]
            ]
        )

        # Merge dialogue and system output by timestamp
        dialog_and_output = [
            (index, message)
            for index, message in enumerate(self.session.messages)
            if message.category
            in {
                MessageCategory.DIALOG,
                MessageCategory.SYSTEM_OUTPUT,
                MessageCategory.INTERNAL,
            }
        ]
        # Category buckets must not reorder a native assistant declaration and
        # its tool results when timestamps are equal/coarse.  Original session
        # index is the stable tie-breaker for provider replay integrity.
        dialog_and_output.sort(key=lambda item: (item[1].timestamp, item[0]))

        def _tool_records_by_call_id(name: str) -> Dict[str, Dict[str, Any]]:
            records = getattr(self.session, name, [])
            if not isinstance(records, list):
                return {}
            return {
                str(record.get("call_id") or "").strip(): record
                for record in records
                if isinstance(record, dict) and str(record.get("call_id") or "").strip()
            }

        def _render_tool_arguments(arguments: Any) -> str:
            if isinstance(arguments, str):
                return arguments if arguments.strip() else "{}"
            if arguments is None:
                return "{}"
            try:
                return json.dumps(arguments, sort_keys=True)
            except Exception:
                return str(arguments)

        tool_call_records = _tool_records_by_call_id("tool_call_records")
        tool_result_records = _tool_records_by_call_id("tool_result_records")

        # Add merged messages
        for _index, msg in dialog_and_output:
            # --- START MODIFICATION: Handle 'tool' role ---
            if msg.role == "tool":
                tool_call_id = str(msg.metadata.get("tool_call_id", "")).strip()
                call_record = tool_call_records.get(tool_call_id, {})
                result_record = tool_result_records.get(tool_call_id, {})
                action_type = (
                    msg.metadata.get("action_type")
                    or msg.metadata.get("name")
                    or call_record.get("name")
                )
                tool_arguments = msg.metadata.get("tool_arguments")
                if tool_arguments is None:
                    tool_arguments = call_record.get("arguments")
                # For 'tool' role, the API expects 'tool_call_id' and 'content'
                api_msg = {
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "content": msg.content,
                }
                # Optionally add 'name' if the action_type is available
                if action_type:
                    api_msg["name"] = action_type
                if tool_arguments is not None:
                    api_msg["tool_arguments"] = _render_tool_arguments(tool_arguments)
                status = msg.metadata.get("status") or result_record.get("status")
                if status:
                    api_msg["status"] = status
                messages.append(api_msg)
            else:
                # Standard message format
                api_msg = {"role": msg.role, "content": msg.content}
                if msg.role == "assistant" and isinstance(msg.metadata, dict):
                    tool_calls = msg.metadata.get("tool_calls")
                    if isinstance(tool_calls, list) and tool_calls:
                        api_msg["tool_calls"] = tool_calls
                messages.append(api_msg)
            # --- END MODIFICATION ---

        messages = [
            message
            for message in sanitize_native_tool_messages(messages)
            if isinstance(message, dict)
        ]

        # If no messages, add a default user message to prevent API errors
        if not messages:
            messages.append(
                {"role": "user", "content": "Placeholder message to prevent API errors"}
            )

        # --- Add logging here ---
        # try:
        #     # Use json.dumps for potentially complex content structures
        #     messages_json = json.dumps(messages, indent=2)
        #     logger.debug(f"Formatted messages being sent to LLM:\n{messages_json}")
        # except Exception as e:
        #     logger.error(f"Error logging formatted messages: {e}") # Log formatting errors too
        # --- End logging ---

        record_runtime_duration(
            "context.format_messages",
            (time.perf_counter() - assembly_started) * 1000,
        )
        return messages

    def _format_context_content_for_model(self, message: Message) -> Any:
        """Format context messages with source metadata visible to the model."""
        if not isinstance(message.content, str):
            return message.content

        metadata = message.metadata if isinstance(message.metadata, dict) else {}
        source = metadata.get("source")
        if not isinstance(source, str) or not source.strip():
            return message.content

        escaped_source = html.escape(source.strip(), quote=True)
        return f'<context source="{escaped_source}">\n{message.content}\n</context>'

    def save(self) -> bool:
        """
        Save the current session through session manager.

        Returns:
            True if successful, False otherwise
        """
        if not self._modified:
            return True

        if self.session_manager:
            success = self.session_manager.save_session(self.session)
            if success:
                self._modified = False
            return success
        return False

    def load(self, session_id: str) -> bool:
        """
        Load a session by ID via session manager, or create a new one if it doesn't exist.

        Args:
            session_id: ID of the session to load

        Returns:
            True if successful (loaded or created), False on error
        """
        if not self.session_manager:
            logger.error("Cannot load: No session manager available")
            return False

        loaded_session = self.session_manager.load_session(session_id)
        if loaded_session:
            self.session = loaded_session
            before_native_sanitization = self.session.to_dict()
            self.session = sanitize_native_tool_session(self.session)
            self._modified = self.session.to_dict() != before_native_sanitization
            # Update sent status
            self.system_prompt_sent = any(
                msg.category == MessageCategory.SYSTEM for msg in self.session.messages
            )
            logger.debug(f"Loaded existing session: {session_id}")
            return True
        else:
            # Session doesn't exist - create a new one with this ID
            logger.info(f"Session {session_id} not found, creating new session")
            self.session = Session(id=session_id)
            self._modified = True  # Mark as modified so it gets saved
            self.system_prompt_sent = False
            return True

    def load_context_file(self, file_path: str) -> bool:
        """Load a context file into the conversation.

        Args:
            file_path: Path to the file to load

        Returns:
            True if successful, False otherwise
        """
        try:
            from penguin.config import WORKSPACE_PATH, config as global_config

            # Try multiple locations
            search_locations = [
                Path(WORKSPACE_PATH) / "context" / file_path,
                Path(file_path),  # Current directory
            ]

            # Try project root if enabled
            context_config = global_config.get("context", {})
            if context_config.get("load_from_project", True):
                try:
                    import subprocess

                    result = subprocess.run(
                        ["git", "rev-parse", "--show-toplevel"],
                        capture_output=True,
                        text=True,
                        cwd=".",
                    )
                    if result.returncode == 0:
                        project_root = Path(result.stdout.strip())
                        search_locations.append(project_root / file_path)
                except Exception:
                    pass

            # Try each location
            for full_path in search_locations:
                if full_path.exists() and full_path.is_file():
                    with open(full_path, "r", encoding="utf-8") as f:
                        content = f.read()

                    self.add_context(content, source=file_path)
                    logger.info(f"Loaded context file: {file_path} (from {full_path})")
                    return True

            logger.warning(f"Context file not found in any location: {file_path}")
            return False
        except Exception as e:
            logger.error(f"Error loading context file {file_path}: {str(e)}")
            return False

            with open(full_path, "r", encoding="utf-8") as f:
                content = f.read()

            self.add_context(content, source=file_path)
            logger.info(f"Loaded context file: {file_path}")
            return True
        except Exception as e:
            logger.error(f"Error loading context file {file_path}: {str(e)}")
            return False

    def list_context_files(self) -> List[Dict[str, Any]]:
        """List available context files in workspace and project.

        Returns:
            List of file information dictionaries
        """
        from penguin.config import WORKSPACE_PATH, config as global_config

        context_config = global_config.get("context", {})
        load_from_project = context_config.get("load_from_project", True)

        files = []

        # 1. List files from context/ folder
        context_dir = Path(WORKSPACE_PATH) / "context"
        if context_dir.exists():
            for entry in context_dir.iterdir():
                if entry.is_file() and not entry.name.startswith("."):
                    files.append(
                        {
                            "path": f"context/{entry.name}",
                            "name": entry.name,
                            "location": "workspace_context",
                            "size": entry.stat().st_size,
                            "modified": datetime.fromtimestamp(
                                entry.stat().st_mtime
                            ).isoformat(),
                        }
                    )

        # 2. List files from project root (if enabled)
        if load_from_project:
            try:
                import subprocess

                result = subprocess.run(
                    ["git", "rev-parse", "--show-toplevel"],
                    capture_output=True,
                    text=True,
                    cwd=".",
                )
                if result.returncode == 0:
                    project_root = Path(result.stdout.strip())
                    doc_files = [
                        "README.md",
                        "ARCHITECTURE.md",
                        "architecture.md",
                        "AGENTS.md",
                        "PENGUIN.md",
                        "CONTRIBUTING.md",
                    ]
                    for doc_file in doc_files:
                        doc_path = project_root / doc_file
                        if doc_path.exists() and doc_path.is_file():
                            if not any(f["name"] == doc_file for f in files):
                                files.append(
                                    {
                                        "path": doc_file,
                                        "name": doc_file,
                                        "location": "project_root",
                                        "size": doc_path.stat().st_size,
                                        "modified": datetime.fromtimestamp(
                                            doc_path.stat().st_mtime
                                        ).isoformat(),
                                    }
                                )
            except Exception as e:
                logger.debug(f"Could not list project files: {e}")

        files.sort(key=lambda x: x["name"])
        return files

    def reset(self) -> None:
        """Reset the conversation state with a new empty session."""
        self.session = Session()
        self.system_prompt_sent = False
        self._modified = True

        if self.session_manager:
            self.session_manager.current_session = self.session
