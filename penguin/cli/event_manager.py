"""
Event Manager - Handle event routing and processing.

Extracted from PenguinCLI during Phase 4, Stage 4.
"""

from typing import Dict, Any, List, Set
from penguin.system.state import MessageCategory


class EventManager:
    """Manages event routing and processing for CLI.

    Handles:
    - Conversation commands
    - Message events
    - Streaming chunk events
    - Session management events
    - Status events
    - Tool events
    - Interrupt events
    - Error events
    """

    def __init__(self, cli_instance):
        """Initialize EventManager.

        Args:
            cli_instance: PenguinCLI instance for callbacks
        """
        self.cli = cli_instance

    def handle_conversation_command(self, command: str, args: List[str]) -> None:
        """Handle conversation-related commands.

        Args:
            command: Command name
            args: Command arguments
        """
        if command == "checkpoints":
            # Display checkpoints
            response = self.cli.core.list_checkpoints()
            self.cli.display_manager.display_checkpoints_response(response)
        elif command == "token-usage":
            # Display token usage
            response = self.cli.core.get_token_usage()
            self.cli.display_manager.display_token_usage_response(response)
        elif command == "truncations":
            # Display truncations
            response = self.cli.core.get_truncations()
            self.cli.display_manager.display_truncations_response(response)
        elif command == "clear":
            # Clear conversation
            self.cli.core.clear_conversation()
            self.cli.display_manager.display_message("Conversation cleared", "system")
        elif command == "save":
            # Save conversation
            checkpoint_id = self.cli.core.save_conversation()
            self.cli.display_manager.display_message(f"Conversation saved as checkpoint: {checkpoint_id}", "system")
        elif command == "load":
            # Load conversation
            if args:
                checkpoint_id = args[0]
                self.cli.core.load_conversation(checkpoint_id)
                self.cli.display_manager.display_message(f"Conversation loaded from checkpoint: {checkpoint_id}", "system")
            else:
                self.cli.display_manager.display_message("Usage: /load <checkpoint_id>", "system")
        else:
            self.cli.display_manager.display_message(f"Unknown command: {command}", "system")

    def handle_message_event(self, event_type: str, data: Dict[str, Any]) -> None:
        """Handle message events for displaying conversation messages.

        Args:
            event_type: Event type
            data: Event data
        """
        role = data.get("role", "unknown")
        message_content = data.get("content", "")
        category = data.get("category", MessageCategory.DIALOG)
        metadata = data.get("metadata", {}) if isinstance(data, dict) else {}

        # Buffer system output messages (tool results) if streaming is active
        if (
            category == MessageCategory.SYSTEM_OUTPUT
            or category == "SYSTEM_OUTPUT"
        ):
            if not self.cli.show_tool_results:
                return
            # Check if this is a verbose tool result that should be suppressed
            tool_name = metadata.get("tool_name", "")
            action_type = metadata.get("action_type", "")

            # Suppress verbose tool output (reads, lists, writes)
            SUPPRESS_VERBOSE_TOOLS = {
                "read_file", "enhanced_read", "list_files_filtered",
                "write_file", "enhanced_write", "list_files"
            }

            if tool_name in SUPPRESS_VERBOSE_TOOLS or action_type in SUPPRESS_VERBOSE_TOOLS:
                # Show compact summary instead of full output
                summary = self.cli._create_tool_summary(tool_name or action_type, message_content, metadata)
                if summary:
                    if self.cli.streaming_manager.is_streaming or self.cli.streaming_manager._active_stream_id is not None:
                        self.cli.pending_system_messages.append((summary, "system"))
                    else:
                        self.cli.display_manager.display_message(summary, "system")
                return

            # Show full output for important tools (execute, diff, etc.)
            if self.cli.streaming_manager.is_streaming or self.cli.streaming_manager._active_stream_id is not None:
                # Buffer for display after streaming completes
                self.cli.pending_system_messages.append((message_content, "system"))
                return
            else:
                # Not streaming, display immediately
                self.cli.display_manager.display_message(message_content, "system")
                return

        # Skip other internal system messages
        if category == MessageCategory.SYSTEM or category == "SYSTEM":
            return

        # Suppress verbose tool payloads for read actions; action results already summarized
        if (
            role == "tool"
            and isinstance(metadata, dict)
            and metadata.get("action_type") in self.cli.FILE_READ_ACTIONS
        ):
            msg_key = f"{role}:{message_content[:50]}"
            self.cli.processed_messages.add(msg_key)
            self.cli.message_turn_map[msg_key] = self.cli.current_conversation_turn
            return

        # Generate a message key and check if we've already processed this message
        msg_key = f"{role}:{message_content[:50]}"
        incoming_normalized = (
            self.cli._normalize_message_content(message_content)
            if role == "assistant"
            else ""
        )
        if msg_key in self.cli.processed_messages:
            return

        # If this is a user message, it's start of a new conversation turn
        if role == "user":
            # Increment conversation turn counter
            self.cli.current_conversation_turn += 1

            # Clear streaming state for new turn
            self.cli.streaming_manager.set_streaming(False)
            self.cli.streaming_manager.streaming_buffer = ""
            self.cli.streaming_manager.streaming_reasoning_buffer = ""
            self.cli.last_completed_message = ""
            self.cli.last_completed_message_normalized = ""

        # For assistant messages, check if this was already displayed via streaming
        if role == "assistant":
            # Skip if this message was already displayed via streaming
            # Use startswith to handle minor formatting differences
            if self.cli.last_completed_message and (
                message_content == self.cli.last_completed_message or
                message_content.startswith(self.cli.last_completed_message[:50]) or
                self.cli.last_completed_message.startswith(message_content[:50])
            ):
                # Add to processed messages to avoid future duplicates
                self.cli.processed_messages.add(msg_key)
                self.cli.message_turn_map[msg_key] = self.cli.current_conversation_turn
                return

            if (
                self.cli.last_completed_message_normalized
                and incoming_normalized
                and incoming_normalized == self.cli.last_completed_message_normalized
            ):
                self.cli.processed_messages.add(msg_key)
                self.cli.message_turn_map[msg_key] = self.cli.current_conversation_turn
                return

        # Add to processed messages and map to current turn
        self.cli.processed_messages.add(msg_key)
        self.cli.message_turn_map[msg_key] = self.cli.current_conversation_turn

        # Display message
        self.cli.display_manager.display_message(message_content, role)

        if role == "assistant":
            self.cli.last_completed_message = message_content
            self.cli.last_completed_message_normalized = incoming_normalized

    def handle_stream_chunk_event(self, event_type: str, data: Dict[str, Any]) -> None:
        """Handle stream_chunk events for live text streaming.

        Args:
            event_type: Event type
            data: Event data
        """
        stream_id = data.get("stream_id")
        chunk = data.get("chunk", "")
        is_final = data.get("is_final", False)
        self.cli.streaming_manager.streaming_role = data.get("role", "assistant")
        is_reasoning = data.get("is_reasoning", False)

        # Ignore chunks with no stream_id (should not happen after refactor)
        if stream_id is None:
            return

        # First chunk of a new streaming message -> start StreamingDisplay
        if self.cli.streaming_manager._active_stream_id is None:
            self.cli.streaming_manager._active_stream_id = stream_id
            self.cli._streaming_started = True
            self.cli.streaming_manager.set_streaming(True)
            self.cli.streaming_manager.streaming_buffer = ""
            self.cli.streaming_manager.streaming_reasoning_buffer = ""

            # CRITICAL: Stop ALL active progress displays FIRST
            self.cli.streaming_manager.safely_stop_progress()

            # Stop the "Thinking..." indicator from chat_loop
            if hasattr(self.cli, "_thinking_progress"):
                try:
                    self.cli._thinking_progress.stop()
                    delattr(self.cli, "_thinking_progress")
                except Exception:
                    pass

            # Start new streaming display with Rich.Live
            self.cli.streaming_display.start_message(role=self.cli.streaming_manager.streaming_role)

        # Ignore chunks that belong to an old or foreign stream
        if stream_id != self.cli.streaming_manager._active_stream_id:
            return

        # Skip empty non-final chunks
        if not chunk and not is_final:
            return

        # Process chunk for display
        if chunk:
            # Append to buffers for deduplication tracking
            if is_reasoning:
                self.cli.streaming_manager.streaming_reasoning_buffer += chunk
            else:
                self.cli.streaming_manager.streaming_buffer += chunk

            # Append to StreamingDisplay
            self.cli.streaming_display.append_text(chunk, is_reasoning=is_reasoning)

        if is_final:
            # Final chunk received - finalize streaming
            self.cli.streaming_manager.set_streaming(False)

            # Filter verbose code blocks before finalizing
            if self.cli.streaming_manager.streaming_buffer:
                filtered_buffer = self.cli._filter_verbose_code_blocks(self.cli.streaming_manager.streaming_buffer)
                # Update the display's content buffer with filtered version
                self.cli.streaming_display.content_buffer = filtered_buffer

            # Stop streaming display (will show final formatted version)
            self.cli.streaming_display.stop(finalize=True)

            # Store for deduplication
            if self.cli.streaming_manager.streaming_buffer.strip():
                self.cli.last_completed_message = self.cli.streaming_manager.streaming_buffer
                self.cli.last_completed_message_normalized = (
                    self.cli._normalize_message_content(self.cli.streaming_manager.streaming_buffer)
                )

            # NOW display any pending system messages (tool results) that arrived during streaming
            if self.cli.pending_system_messages:
                for msg_content, msg_role in self.cli.pending_system_messages:
                    self.cli.display_manager.display_message(msg_content, msg_role)
                self.cli.pending_system_messages.clear()

            # Clear stream ID
            self.cli.streaming_manager._active_stream_id = None

            # Store completed message for deduplication
            if self.cli.streaming_manager.streaming_buffer.strip():
                completed_msg_key = (
                    f"{self.cli.streaming_manager.streaming_role}:{self.cli.streaming_manager.streaming_buffer[:50]}"
                )
                self.cli.processed_messages.add(completed_msg_key)
                self.cli.message_turn_map[completed_msg_key] = (
                    self.cli.current_conversation_turn
                )

            # Reset buffers
            self.cli.streaming_manager.streaming_buffer = ""
            self.cli.streaming_manager.streaming_reasoning_buffer = ""
            return

    def handle_session_management(self, command: str, args: List[str]) -> None:
        """Handle session management commands.

        Args:
            command: Command name
            args: Command arguments
        """
        if command == "new":
            # Create new session
            self.cli.core.new_conversation()
            self.cli.display_manager.display_message("New conversation started", "system")
        elif command == "clear":
            # Clear conversation
            self.cli.core.clear_conversation()
            self.cli.display_manager.display_message("Conversation cleared", "system")
        elif command == "save":
            # Save conversation
            checkpoint_id = self.cli.core.save_conversation()
            self.cli.display_manager.display_message(f"Conversation saved as checkpoint: {checkpoint_id}", "system")
        elif command == "load":
            # Load conversation
            if args:
                checkpoint_id = args[0]
                self.cli.core.load_conversation(checkpoint_id)
                self.cli.display_manager.display_message(f"Conversation loaded from checkpoint: {checkpoint_id}", "system")
            else:
                self.cli.display_manager.display_message("Usage: /load <checkpoint_id>", "system")
        elif command == "list":
            # List checkpoints
            response = self.cli.core.list_checkpoints()
            self.cli.display_manager.display_checkpoints_response(response)
        else:
            self.cli.display_manager.display_message(f"Unknown session command: {command}", "system")

    def handle_status_event(self, event_type: str, data: Dict[str, Any]) -> None:
        """Handle status events like RunMode updates.

        Args:
            event_type: Event type
            data: Event data
        """
        status_type = data.get("status_type", "")

        # Update RunMode status
        if "task_started" in status_type:
            self.cli.run_mode_active = True
            task_name = data.get("data", {}).get("task_name", "Unknown task")
            self.cli.run_mode_status = f"Task '{task_name}' started"

            # CRITICAL: Reset streaming state when RunMode starts to avoid conflicts
            self.cli.streaming_manager.finalize_streaming()

            # Update streaming display status
            if self.cli.streaming_display.is_active:
                self.cli.streaming_display.set_status(f"Starting task: {task_name}")
            else:
                self.cli.display_manager.display_message(f"Starting task: {task_name}", "system")

        elif "task_progress" in status_type:
            self.cli.run_mode_active = True
            iteration = data.get("data", {}).get("iteration", "?")
            max_iter = data.get("data", {}).get("max_iterations", "?")
            progress = data.get("data", {}).get("progress", 0)
            self.cli.run_mode_status = (
                f"Progress: {progress}% (Iter: {iteration}/{max_iter})"
            )

            # Update streaming display if active
            if self.cli.streaming_display.is_active:
                self.cli.streaming_display.set_status(self.cli.run_mode_status)

        elif "task_completed" in status_type or "run_mode_ended" in status_type:
            self.cli.run_mode_active = False

            # CRITICAL: Finalize any active streaming when task completes
            if self.cli.streaming_manager._active_stream_id is not None or self.cli.streaming_manager.is_streaming:
                self.cli.streaming_manager.finalize_streaming()

            # Clear streaming display status
            if self.cli.streaming_display.is_active:
                self.cli.streaming_display.clear_status()

            if "task_completed" in status_type:
                task_name = data.get("data", {}).get(
                    "task_name", "Unknown task"
                )
                self.cli.run_mode_status = f"Task '{task_name}' completed"
                self.cli.display_manager.display_message(f"Task '{task_name}' completed", "system")
            else:
                self.cli.run_mode_status = "RunMode ended"
                self.cli.display_manager.display_message("RunMode ended", "system")

        elif "clarification_needed" in status_type:
            self.cli.run_mode_active = True
            prompt = data.get("data", {}).get("prompt", "Input needed")
            self.cli.run_mode_status = f"Clarification needed: {prompt}"

            # Update streaming display if active
            if self.cli.streaming_display.is_active:
                self.cli.streaming_display.set_status(self.cli.run_mode_status)
            else:
                self.cli.display_manager.display_message(f"Clarification needed: {prompt}", "system")

    def handle_tool_event(self, event_type: str, data: Dict[str, Any]) -> None:
        """Handle tool execution events.

        Args:
            event_type: Event type
            data: Event data
        """
        phase = data.get("phase", "")
        tool_name = data.get("action", data.get("tool_name", ""))

        if phase == "start" and tool_name:
            # Show tool execution indicator
            if self.cli.streaming_display.is_active:
                self.cli.streaming_display.set_tool(tool_name)

        elif phase == "end":
            # Clear tool indicator
            if self.cli.streaming_display.is_active:
                self.cli.streaming_display.clear_tool()

            # Optionally display tool result (if not verbose)
            result = data.get("result", "")
            if result and not self.cli.streaming_manager.is_streaming:
                # Only show if not currently streaming assistant response
                tool_summary = f"✓ {tool_name}" if len(result) < 50 else f"✓ {tool_name}: {result[:47]}..."
                self.cli.display_manager.display_message(tool_summary, "system")

    def handle_interrupt(self, event_type: str, data: Dict[str, Any]) -> None:
        """Handle interrupt events.

        Args:
            event_type: Event type
            data: Event data
        """
        # Stop any active streaming
        self.cli.streaming_manager.finalize_streaming()

        # Display interrupt message
        self.cli.display_manager.display_message("⚠️ Interrupted by user", "system")

    def handle_error_event(self, event_type: str, data: Dict[str, Any]) -> None:
        """Handle error events.

        Args:
            event_type: Event type
            data: Event data
        """
        error_msg = data.get("message", "Unknown error")
        source = data.get("source", "")
        details = data.get("details", "")

        # Display error message
        self.cli.display_manager.display_message(f"Error: {error_msg}\n{details}", "error")
