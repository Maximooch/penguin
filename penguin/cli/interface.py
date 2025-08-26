import asyncio
import traceback
import httpx # Added for making async HTTP requests # type: ignore
from datetime import datetime
from typing import Any, Dict, List, Optional, Callable, Tuple, Awaitable
import json
from pathlib import Path
import os
import shutil
import concurrent.futures

import logging

logger = logging.getLogger(__name__)

from rich.console import Console # type: ignore

from penguin.core import PenguinCore
from penguin.system.state import parse_iso_datetime, MessageCategory
from penguin.system.conversation_menu import ConversationMenu, ConversationSummary

class PenguinInterface:
    """Handles all CLI business logic and core integration"""
    
    def __init__(self, core: PenguinCore):
        self.core = core
        # Create a default console for conversation menu
        self.console = Console()
        self.conversation_menu = ConversationMenu(self.console)
        self._active = True
        self.message_count = 0
        self.in_247_mode = False
        self._progress_callbacks: List[Callable[[int, int, Optional[str]], None]] = []
        self._token_callbacks: List[Callable[[Dict[str, Any]], None]] = []
        
        # Initialize with safe defaults
        try:
            # Delay streaming setting initialisation until model_config is available
            if hasattr(self.core, 'model_config') and self.core.model_config is not None:
                self._initialize_streaming_settings()
            
            # Register for progress updates from core
            if hasattr(self.core, 'register_progress_callback') and callable(self.core.register_progress_callback):
                self.core.register_progress_callback(self._on_progress_update)
            else:
                print(f"[Interface] Warning: core.register_progress_callback not found or not callable.")
            
            # Register for token updates from core (assuming this method will be added to PenguinCore)
            # REMOVED: This was causing a warning as PenguinCore doesn't have this method yet.
            # The interface manages its own token callbacks which the CLI uses.
            # if hasattr(self.core, 'register_token_callback') and callable(self.core.register_token_callback):
            #     self.core.register_token_callback(self._on_token_update)
            # else:
            #     print(f"[Interface] Warning: core.register_token_callback not found or not callable. Token UI may not update.")
            
            # Initial token update
            self.update_token_display()
        except Exception as e:
            print(f"[Interface] Warning: Error during initialization: {e}\\n{traceback.format_exc()}")
            # Continue despite errors - we want the interface to be as resilient as possible

    def register_progress_callback(self, callback: Callable[[int, int, Optional[str]], None]) -> None:
        """Register callback for progress updates"""
        self._progress_callbacks.append(callback)
        
    def register_token_callback(self, callback: Callable[[Dict[str, Any]], None]) -> None:
        """Register callback for token usage updates"""
        import logging
        logging.getLogger(__name__).debug(
            "Registering token callback: %s",
            getattr(callback, "__qualname__", str(callback))
        )
        self._token_callbacks.append(callback)
        
    def _on_progress_update(self, iteration: int, max_iterations: int, message: Optional[str] = None) -> None:
        """Handle progress updates from core and forward to UI"""
        for callback in self._progress_callbacks:
            try:
                callback(iteration, max_iterations, message)
            except Exception as e:
                print(f"[Interface] Error in progress callback: {e}\\n{traceback.format_exc()}")
            
    def _on_token_update(self, usage: Dict[str, Any]) -> None:
        """Handle token updates from core and forward to UI"""
        # Expected usage keys from ConversationManager: "prompt_tokens", "completion_tokens", "total_tokens", "max_tokens"
        # No transformation should be needed if ConversationManager provides these directly.
        
        # Forward the token usage to UI callbacks
        for callback in self._token_callbacks:
            try:
                callback(usage)
            except Exception as e:
                print(f"[Interface] Error in token callback: {e}\\n{traceback.format_exc()}")
            
    def get_token_usage(self) -> Dict[str, Any]:
        """Get current token usage statistics from the ConversationManager.
        This method now expects a specific format focused on the active context window.
        Output format expected from ConversationManager (via ContextWindowManager):
        {
            "current_total_tokens": ..., 
            "max_tokens": ...,       
            "categories": {
                "SYSTEM": ..., ... 
            }
        }
        """
        default_usage = {
            "current_total_tokens": 0,
            "max_tokens": self.core.model_config.max_tokens if hasattr(self.core, 'model_config') and self.core.model_config else 200000,
            "categories": {cat.name: 0 for cat in MessageCategory},
            "error": "No data from ConversationManager"
        }
        try:
            if not hasattr(self.core, 'conversation_manager') or not self.core.conversation_manager:
                print("[Interface] Warning: core.conversation_manager not found.")
                return default_usage
            
            # This should now return the standardized dict from ContextWindowManager
            usage_from_manager = self.core.conversation_manager.get_token_usage()
            
            # Validate the received structure (basic check)
            if isinstance(usage_from_manager, dict) and \
               "current_total_tokens" in usage_from_manager and \
               "max_tokens" in usage_from_manager and \
               "categories" in usage_from_manager and isinstance(usage_from_manager["categories"], dict):
                
                # Add a percentage calculation for convenience
                current_total = usage_from_manager["current_total_tokens"]
                max_t = usage_from_manager["max_tokens"]
                usage_from_manager["percentage"] = (current_total / max_t * 100) if max_t > 0 else 0
                return usage_from_manager
            else:
                print(f"[Interface] Warning: Unexpected token usage format from conversation_manager: {usage_from_manager}")
                default_usage["error"] = f"Unexpected format: {str(usage_from_manager)[:100]}..."
                return default_usage
        except Exception as e:
            print(f"[Interface] Error getting token usage: {e}\n{traceback.format_exc()}")
            default_usage["error"] = str(e)
            return default_usage

    def update_token_display(self) -> None:
        """Update token usage display by notifying callbacks."""
        # This method now directly passes the detailed usage dictionary to callbacks.
        # The UI (or test script) will be responsible for formatting this data.
        usage_data = self.get_token_usage() # This now gets the more structured data
        for callback in self._token_callbacks:
            try:
                callback(usage_data) # Pass the whole dict
            except Exception as e:
                print(f"[Interface] Error in token callback: {e}")

    def get_streaming_message(self) -> Optional[Dict[str, Any]]:
        """
        Gets the current streaming message from Core, if any.
        
        Returns:
            Dict with message fields if streaming is active, None otherwise
        """
        # Rely on Core's streaming state management
        if hasattr(self.core, 'get_streaming_message'):
            return self.core.get_streaming_message()
        return None

    def get_conversation_messages(self) -> List[Dict[str, Any]]:
        """
        Gets all messages in the current conversation.
        
        Returns:
            List of message dictionaries
        """
        # Use ConversationManager as the single source of truth
        if hasattr(self.core, 'conversation_manager') and self.core.conversation_manager:
            cm = self.core.conversation_manager
            messages = []
            
            if hasattr(cm, 'conversation') and cm.conversation:
                # Direct access to session messages instead of non-existent get_all_messages()
                if hasattr(cm.conversation, 'session') and cm.conversation.session:
                    # Convert ConversationManager Message objects to dicts
                    for msg in cm.conversation.session.messages:
                        messages.append({
                            "role": msg.role,
                            "content": msg.content,
                            "category": msg.category,
                            "timestamp": msg.timestamp,
                            "metadata": msg.metadata if hasattr(msg, 'metadata') else {}
                        })
            
            return messages
        
        # Fallback to empty list if conversation manager not available
        return []

    def get_runmode_status(self) -> Dict[str, Any]:
        """
        Get the current RunMode status information for UI display.
        
        Returns:
            Dictionary with RunMode status information
        """
        result = {
            "active": False,
            "summary": "RunMode inactive",
            "task_name": None,
            "continuous": False
        }
        
        # Get summary from Core if available
        if hasattr(self.core, 'current_runmode_status_summary'):
            result["summary"] = self.core.current_runmode_status_summary
            # If we have a summary that's not the idle message, RunMode is likely active
            result["active"] = self.core.current_runmode_status_summary != "RunMode idle."
            
        # Get additional status from Core.run_mode if available
        if hasattr(self.core, 'run_mode') and self.core.run_mode:
            result["active"] = True
            if hasattr(self.core.run_mode, 'continuous_mode'):
                result["continuous"] = self.core.run_mode.continuous_mode
            if hasattr(self.core.run_mode, 'current_task_name'):
                result["task_name"] = self.core.run_mode.current_task_name
                
        return result

    def get_detailed_token_usage(self) -> Dict[str, Any]:
        """Returns the detailed token usage, now sourced from get_token_usage."""
        # This method can be expanded later if we need to add more details 
        # (e.g., per-API-call prompt/completion tokens, cost) that are not part
        # of the basic context window stats.
        base_usage = self.get_token_usage()
        
        # Example of adding more data if available from core (conceptual)
        # if hasattr(self.core, 'last_api_call_stats'):
        #    base_usage['last_call_prompt_tokens'] = self.core.last_api_call_stats.get('prompt')
        #    base_usage['last_call_completion_tokens'] = self.core.last_api_call_stats.get('completion')
        #    base_usage['last_call_cost'] = self.core.last_api_call_stats.get('cost')

        return base_usage

    async def process_input(self, input_data: Dict[str, Any], stream_callback: Optional[Callable[[str], None]] = None) -> Dict[str, Any]:
        """
        Process a user input message and generate a response.
        
        Args:
            input_data: Dictionary containing the user input, with at least a 'text' key
            stream_callback: Optional callback for streaming response chunks
            
        Returns:
            Dictionary containing the core response with assistant_response and action_results
        """
        try:
            logger.debug(f"Processing input: {input_data}")
            
            # Extract input text
            input_text = input_data.get('text', '')
            if not input_text.strip():
                logger.warning("Empty input text received")
                return {"assistant_response": "No input provided", "action_results": []}
            
            # Prepare the input data dictionary
            input_data_dict = input_data
            logger.debug(f"Input data dict prepared: {input_data_dict}")
            
            # Always enable streaming for better UX, but rely on event system for display
            # The stream_callback is only for legacy compatibility
            streaming_enabled = True
            
            # Process the input using Core
            logger.debug(f"Calling core.process with streaming={streaming_enabled}")
            try:
                # FIXED: Don't use thread pool for now - it causes event loop conflicts
                # The core.process emits events back to the TUI which expect to be on the same loop
                # TODO: Revisit this optimization once we fully decouple Core from TUI event loops
                response = await self.core.process(
                    input_data_dict,
                    streaming=streaming_enabled,
                    stream_callback=None  # Let event system handle display
                )
                    
                logger.debug(f"Core.process completed with response keys: {response.keys() if isinstance(response, dict) else 'not a dict'}")
            except Exception as e:
                logger.error(f"Error in core.process: {str(e)}", exc_info=True)
                return {
                    "assistant_response": f"Error in core processing: {str(e)}",
                    "action_results": [],
                    "error": str(e)
                }
            
            # Note: No need to manually finalize streaming - Core handles this via events
            
            # Update token display to show latest stats
            logger.debug("Updating token display")
            self.update_token_display()
            
            # Normalize action results to ensure CLI can display them properly
            if isinstance(response, dict) and "action_results" in response:
                response["action_results"] = self._normalize_action_results(response["action_results"])
                logger.debug(f"Normalized action results: {response['action_results']}")
            
            return response
            
        except Exception as e:
            error_msg = f"Error processing input: {str(e)}"
            logger.error(error_msg, exc_info=True)
            return {
                "assistant_response": error_msg,
                "action_results": [],
                "error": str(e)
            }
            
    def _normalize_action_results(self, action_results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Normalize action results to ensure they have all the fields needed by the CLI.
        
        This handles differences in field naming between Engine/Core and what CLI expects.
        
        Args:
            action_results: List of action result dictionaries
            
        Returns:
            List of normalized action result dictionaries
        """
        normalized_results = []
        
        for result in action_results:
            if not isinstance(result, dict):
                # Handle non-dict results by wrapping them
                normalized_results.append({
                    "action": "unknown",
                    "result": str(result),
                    "status": "completed"
                })
                continue
                
            # Create a copy to avoid modifying the original
            normalized = result.copy()
            
            # Handle field name differences (Engine uses action_name, CLI expects action)
            if "action_name" in normalized and "action" not in normalized:
                normalized["action"] = normalized["action_name"]
                
            # Handle output field (Engine uses output, CLI expects result)
            if "output" in normalized and "result" not in normalized:
                normalized["result"] = normalized["output"]
                
            # Ensure required fields are present
            if "action" not in normalized:
                normalized["action"] = normalized.get("type", "unknown")
                
            if "result" not in normalized:
                normalized["result"] = normalized.get("message", "(No output available)")
                
            if "status" not in normalized:
                normalized["status"] = "completed"
                
            normalized_results.append(normalized)
            
        return normalized_results

    async def handle_command(self, command: str, 
                             runmode_stream_cb: Optional[Callable[[str], Awaitable[None]]] = None, 
                             runmode_ui_update_cb: Optional[Callable[[], Awaitable[None]]] = None) -> Dict[str, Any]:
        """Handle slash commands"""
        parts = command.split(" ", 2)
        cmd, args = parts[0].lower(), parts[1:] if len(parts) > 1 else []

        handlers = {
            "chat": self._handle_chat_command,
            "task": self._handle_task_command,
            "project": self._handle_project_command,
            "run": self._handle_run_command,
            "config": self._handle_config_command,
            "list": self._handle_list_command,
            "help": self._handle_help_command,
            "exit": self._handle_exit_command,
            "tokens": self._handle_tokens_command,
            "context": self._handle_context_command,
            "debug": self._handle_debug_command,
            "stream": self._handle_stream_command,  # Added stream command handler
            "model": self._handle_model_command, # For /model set only
            "models": self._handle_models_command, # New simple interactive selector
        }
        
        handler = handlers.get(cmd, self._invalid_command)
        if cmd == "run":
            result = await handler(args, runmode_stream_cb=runmode_stream_cb, runmode_ui_update_cb=runmode_ui_update_cb)
        else:
            # Call other handlers without the runmode-specific callbacks
            result = await handler(args)
        
        # Update token display after command execution
        self.update_token_display()
        
        # Normalize action_results if present for consistent display in CLI
        if isinstance(result, dict) and "action_results" in result:
            result["action_results"] = self._normalize_action_results(result["action_results"])
            
        return result

    async def _handle_chat_command(self, args: List[str]) -> Dict[str, Any]:
        """Handle conversation management commands"""
        if not args:
            return {"error": "Missing chat subcommand"}
            
        subcmd = args[0].lower()
        if subcmd == "list":
            raw_conversations = self.core.list_conversations() # This should come from ConversationManager
            # Convert to ConversationSummary objects for display
            summaries = []
            for conv_data in raw_conversations:
                # Ensure conv_data is a dictionary
                if not isinstance(conv_data, dict):
                    print(f"[Interface] Warning: Expected dict for conversation data, got {type(conv_data)}")
                    continue

                # Extract data from the conversation dictionary
                session_id = conv_data.get("id", f"unknown_id_{datetime.now().timestamp()}")
                # Title might be under 'metadata' or directly
                title = conv_data.get("title")
                if not title and "metadata" in conv_data and isinstance(conv_data["metadata"], dict):
                    title = conv_data["metadata"].get("title")
                if not title:
                    title = f"Conversation {session_id[:8]}" # Fallback title
                
                message_count = conv_data.get("message_count", 0)
                last_active_str = conv_data.get("last_active", datetime.now().isoformat())
                
                try:
                    # Use parse_iso_datetime for robustness if it's available and handles the format
                    last_active_dt = parse_iso_datetime(last_active_str)
                    last_active_formatted = last_active_dt.strftime("%Y-%m-%d %H:%M")
                except Exception: # Catch parsing errors
                    last_active_formatted = last_active_str # Fallback to raw string

                summary = ConversationSummary(
                    session_id=session_id,
                    title=title,
                    message_count=message_count,
                    last_active=last_active_formatted # Use formatted string
                )
                summaries.append(summary)
                
            return {"conversations": summaries}
        elif subcmd == "load" and len(args) > 1:
            return await self._load_conversation(args[1])
        elif subcmd == "summary":
            return {"summary": self.core.conversation_manager.conversation.get_history()}
        return {"error": f"Unknown chat command: {subcmd}"}

    async def _handle_task_command(self, args: List[str]) -> Dict[str, Any]:
        """Handle task management commands"""
        if not args:
            return {"error": "Missing task subcommand"}
            
        action = args[0].lower()
        # --- TASK CREATE ---------------------------------------------------
        # Accept both of the following syntaxes:
        #   /task create <name> <description words...>
        #   /task create "<name with spaces>" "<description words...>"
        # Because _handle_command currently splits the input into **at most**
        # three parts (command, sub-command, remainder) we may receive the
        # *name* **and** *description* combined in args[1].  Therefore we
        # parse the remainder string manually.

        if action == "create" and len(args) >= 2:
            # When the CLI split fails to separate name/description we treat
            # everything after the first whitespace as the description.
            remainder = " ".join(args[1:]) if len(args) > 2 else args[1]

            # Use shlex to honour quotes so users can include spaces in the
            # task name without breaking parsing – e.g. /task create "my game" "cool desc".
            import shlex
            try:
                parts_parsed = shlex.split(remainder)
            except ValueError:
                # Fallback to naive split if shlex fails (unbalanced quotes etc.).
                parts_parsed = remainder.split(" ")

            name = parts_parsed[0] if parts_parsed else ""
            description = " ".join(parts_parsed[1:]) if len(parts_parsed) > 1 else ""

            if not name:
                return {"error": "Task name missing for /task create"}

            try:
                task = await self.core.project_manager.create_task_async(
                    title=name,
                    description=description,
                    priority=1  # Default priority
                )
                return {
                    "status": f"Created task: {task.title}",
                    "task_id": task.id,
                    "task_title": task.title
                }
            except Exception as e:
                return {"error": f"Failed to create task: {str(e)}"}
        elif action == "run" and len(args) > 1:
            return await self.core.start_run_mode(args[1], " ".join(args[2:]))
        elif action == "status" and len(args) > 1:
            try:
                task = await self.core.project_manager.get_task_async(args[1])
                if task:
                    return {
                        "status": f"Task '{task.title}' status: {task.status.value}",
                        "task": {
                            "id": task.id,
                            "title": task.title,
                            "status": task.status.value,
                            "description": task.description,
                            "priority": task.priority,
                            "created_at": task.created_at
                        }
                    }
                else:
                    return {"error": f"Task not found: {args[1]}"}
            except Exception as e:
                return {"error": f"Failed to get task status: {str(e)}"}
        return {"error": f"Unknown task command: {action}"}

    async def _handle_project_command(self, args: List[str]) -> Dict[str, Any]:
        """Handle project management commands"""
        if not args:
            return {"error": "Missing project subcommand"}
            
        action = args[0].lower()
        # --- PROJECT CREATE ------------------------------------------------
        if action == "create" and len(args) >= 2:
            remainder = " ".join(args[1:]) if len(args) > 2 else args[1]

            import shlex
            try:
                parts_parsed = shlex.split(remainder)
            except ValueError:
                parts_parsed = remainder.split(" ")

            name = parts_parsed[0] if parts_parsed else ""
            description = " ".join(parts_parsed[1:]) if len(parts_parsed) > 1 else ""

            if not name:
                return {"error": "Project name missing for /project create"}

            try:
                project = await self.core.project_manager.create_project_async(
                    name=name,
                    description=description
                )
                return {
                    "status": f"Created project: {project.name}",
                    "project_id": project.id,
                    "project_name": project.name
                }
            except Exception as e:
                return {"error": f"Failed to create project: {str(e)}"}
        elif action == "run" and len(args) > 1:
            return await self.core.start_run_mode(args[1], " ".join(args[2:]), mode_type="project")
        elif action == "status" and len(args) > 1:
            try:
                project = await self.core.project_manager.get_project_async(args[1])
                if project:
                    # Get task summary for this project
                    project_tasks = await self.core.project_manager.list_tasks_async(project_id=project.id)
                    task_summary = {
                        "total": len(project_tasks),
                        "active": len([t for t in project_tasks if t.status.value == "ACTIVE"]),
                        "completed": len([t for t in project_tasks if t.status.value == "COMPLETED"]),
                        "failed": len([t for t in project_tasks if t.status.value == "FAILED"])
                    }
                    
                    return {
                        "status": f"Project '{project.name}' status: {project.status}",
                        "project": {
                            "id": project.id,
                            "name": project.name,
                            "status": project.status,
                            "description": project.description,
                            "created_at": project.created_at,
                            "task_summary": task_summary
                        }
                    }
                else:
                    return {"error": f"Project not found: {args[1]}"}
            except Exception as e:
                return {"error": f"Failed to get project status: {str(e)}"}
        return {"error": f"Unknown project command: {action}"}

    async def _handle_config_command(self, args: List[str]) -> Dict[str, Any]:
        """Handle configuration commands: list|get|set|add|remove

        Usage examples:
          /config list
          /config get model.default
          /config set model.temperature 0.4
          /config add project.additional_directories "/opt/shared"
          /config remove project.additional_directories "/opt/shared"
          /config --global set model.default "openai/gpt-5"
          /config --cwd /path/to/project get model.default
        """
        try:
            if not args:
                return {"error": "Missing config action (list|get|set|add|remove)"}

            # Parse simple flags manually (order-independent for first few tokens)
            scope = "project"
            cwd_override: Optional[str] = None
            tokens: List[str] = []
            i = 0
            while i < len(args):
                tok = args[i]
                if tok in ("--global", "-g", "global"):
                    scope = "global"
                    i += 1
                    continue
                if tok == "--cwd" and i + 1 < len(args):
                    cwd_override = args[i + 1]
                    i += 2
                    continue
                tokens.append(tok)
                i += 1

            if not tokens:
                return {"error": "Missing config action after flags"}

            action = tokens[0].lower()
            key = tokens[1] if len(tokens) > 1 else None
            raw_value = tokens[2] if len(tokens) > 2 else None

            from penguin.config import (
                load_config as _load_config,
                set_config_value as _set_config_value,
                get_config_value as _get_config_value,
            )

            if action == "list":
                cfg = _load_config()
                return {"status": "ok", "config": cfg}

            if action == "get":
                if not key:
                    return {"error": "'get' requires a key"}
                val = _get_config_value(key, default=None, cwd_override=cwd_override)
                return {"status": "ok", "key": key, "value": val}

            if action in ("set", "add", "remove"):
                if not key:
                    return {"error": f"'{action}' requires a key"}
                if action == "set" and raw_value is None:
                    return {"error": "'set' requires a value"}

                # Attempt to parse JSON; fall back to string
                parsed_val: Any = raw_value
                if raw_value is not None:
                    try:
                        parsed_val = json.loads(raw_value)
                    except Exception:
                        parsed_val = raw_value

                list_op = action if action in ("add", "remove") else None
                written_path = _set_config_value(
                    key,
                    parsed_val,
                    scope=scope,
                    cwd_override=cwd_override,
                    list_op=list_op,
                )
                return {
                    "status": "ok",
                    "action": action,
                    "key": key,
                    "value": parsed_val,
                    "written": str(written_path),
                    "scope": scope,
                }

            return {"error": "Unknown config action. Use list|get|set|add|remove"}

        except Exception as e:
            return {"error": f"Config command failed: {str(e)}"}

    async def _handle_run_command(self, args: List[str], 
                                  runmode_stream_cb: Optional[Callable[[str], Awaitable[None]]] = None, 
                                  runmode_ui_update_cb: Optional[Callable[[], Awaitable[None]]] = None) -> Dict[str, Any]:
        """
        Handle RunMode command for executing autonomous tasks.
        
        Args:
            args: Command arguments
            runmode_stream_cb: Optional async callback for streaming output during RunMode
            runmode_ui_update_cb: Optional async callback for UI updates based on RunMode events
            
        Returns:
            Dictionary with command result
        """
        try:
            subcommand = args[0] if args else "help"
            
            # Support flag-style invocation: --247 and optional --time <minutes>
            # If the first arg starts with "--", treat subcommand as flag set.
            if subcommand.startswith("--"):
                # Re-insert subcommand token into args list for unified parsing
                args = [subcommand] + args[1:]
                subcommand = "flags"

            if subcommand == "help":
                return {
                    "status": "RunMode Help:\n"
                            + "/run task [task_name] - Run a specific task\n"
                            + "/run continuous [task_name] - Run continuous mode\n"
                            + "/run stop - Stop current run mode execution"
                }
            
            if subcommand == "stop":
                # Todo: implement stop functionality
                return {"status": "RunMode stop not yet implemented"}
            
            if subcommand in ["task", "continuous", "flags"]:
                # Default values
                continuous_mode = False
                time_limit = None
                task_name = None
                desc = None

                if subcommand == "continuous":
                    continuous_mode = True
                    task_name = args[1] if len(args) > 1 else None
                    desc = " ".join(args[2:]) if len(args) > 2 else None
                else:
                    # Parse flag list ("flags" branch or explicit flags)
                    # Gather remaining tokens in a separate list for task/description
                    remaining: List[str] = []
                    i = 0
                    while i < len(args):
                        token = args[i]
                        if token == "--247":
                            continuous_mode = True
                            i += 1
                            continue
                        if token == "--time" and i + 1 < len(args):
                            try:
                                time_limit = int(args[i + 1])
                            except ValueError:
                                pass
                            i += 2
                            continue
                        remaining.append(token)
                        i += 1

                    if remaining:
                        task_name = remaining[0]
                        if len(remaining) > 1:
                            desc = " ".join(remaining[1:])
                
                # Start run mode with callbacks for UI updates
                await self.core.start_run_mode(
                    name=task_name, 
                    description=desc, 
                    continuous=continuous_mode, 
                    time_limit=time_limit,
                    stream_callback_for_cli=runmode_stream_cb,
                    ui_update_callback_for_cli=runmode_ui_update_cb,
                )
                
                mode_label = "continuous" if continuous_mode else "task"
                return {
                    "status": f"RunMode {mode_label} started: {task_name or 'No specific task'}"
                }
                
            return {"error": f"Unknown run subcommand: {subcommand}"}
            
        except Exception as e:
            logger.exception(f"Error in run command: {e}")
            return self._format_error(e)

    async def _handle_list_command(self, args: List[str]) -> Dict[str, Any]:
        """Handle list command - show projects and tasks"""
        try:
            projects = await self.core.project_manager.list_projects_async()
            all_tasks = await self.core.project_manager.list_tasks_async()
            
            # Format output similar to the old process_list_command
            result = {
                "projects": [],
                "tasks": [],
                "summary": {
                    "total_projects": len(projects),
                    "total_tasks": len(all_tasks),
                    "active_tasks": len([t for t in all_tasks if t.status.value == "ACTIVE"])
                }
            }
            
            # Format projects
            for project in projects:
                project_tasks = [t for t in all_tasks if t.project_id == project.id]
                result["projects"].append({
                    "id": project.id,
                    "name": project.name,
                    "description": project.description,
                    "status": project.status,
                    "task_count": len(project_tasks),
                    "created_at": project.created_at
                })
            
            # Format tasks
            for task in all_tasks:
                result["tasks"].append({
                    "id": task.id,
                    "title": task.title,
                    "description": task.description,
                    "status": task.status.value,
                    "project_id": task.project_id,
                    "priority": task.priority,
                    "created_at": task.created_at
                })
            
            return result
            
        except Exception as e:
            logger.exception(f"Error in list command: {e}")
            return self._format_error(e)

    async def _load_conversation(self, session_id: str) -> Dict[str, Any]:
        """Load conversation by ID"""
        try:
            self.core.conversation_manager.load(session_id)
            return {"status": f"Loaded conversation {session_id}"}
        except Exception as e:
            return {"error": str(e)}

    def _format_error(self, error: Exception) -> Dict[str, Any]:
        """Format error response"""
        return {
            "error": str(error),
            "details": str(traceback.format_exc()),
            "action_results": []
        }

    async def _invalid_command(self, args: List[str]) -> Dict[str, Any]:
        """Handle unknown commands"""
        return {"error": "Invalid command", "suggestions": self._get_command_suggestions()}

    async def _handle_help_command(self, args: List[str]) -> Dict[str, Any]:
        """Handle help command"""
        return {
            "help": "Available Commands",
            "commands": self._get_command_suggestions()
        }
        
    async def _handle_exit_command(self, args: List[str]) -> Dict[str, Any]:
        """Handle exit command"""
        self._active = False
        return {"status": "exit", "message": "Goodbye!"}
        
    async def _handle_tokens_command(self, args: List[str]) -> Dict[str, Any]:
        """Handle tokens command to show or reset token usage"""
        if args and args[0].lower() == "reset":
            # Reset token counters if available
            if hasattr(self.core, 'conversation_manager') and \
               hasattr(self.core.conversation_manager, 'reset_token_usage_for_current_session'): # Hypothetical method
                try:
                    self.core.conversation_manager.reset_token_usage_for_current_session()
                    # Important: also re-fetch and notify UI callbacks
                    self.update_token_display()
                    return {"status": "Token counters for the current session reset successfully."}
                except Exception as e:
                    return {"error": f"Failed to reset token counters: {str(e)}"}
            return {"status": "Token reset function not available or not fully implemented in ConversationManager."}
        elif args and args[0].lower() == "detail":
            # Show detailed token usage by category
            return {"token_usage_detailed": self.get_detailed_token_usage()}
        else:
            # Show standard token usage
            return {"token_usage": self.get_token_usage()}
            
    async def _handle_context_command(self, args: List[str]) -> Dict[str, Any]:
        """Handle context file commands"""
        try:
            if not args:
                return {"context_files": self.core.list_context_files()}
            action = args[0].lower()

            # Basic list/load retained
            if action == "list":
                return {"context_files": self.core.list_context_files()}
            if action == "paths":
                from penguin.utils.path_utils import get_allowed_roots
                import json as _json
                prj_root, ws_root, proj_extra, ctx_extra = get_allowed_roots()
                data = {
                    "project_root": str(prj_root),
                    "workspace_root": str(ws_root),
                    "project_additional": [str(p) for p in proj_extra],
                    "context_additional": [str(p) for p in ctx_extra],
                }
                # Build a simple pretty view for TUI
                lines = [
                    "Paths:",
                    f"- project_root: {data['project_root']}",
                    f"- workspace_root: {data['workspace_root']}",
                    "- project_additional:",
                ]
                if data["project_additional"]:
                    lines.extend([f"  - {p}" for p in data["project_additional"]])
                else:
                    lines.append("  (none)")
                lines.append("- context_additional:")
                if data["context_additional"]:
                    lines.extend([f"  - {p}" for p in data["context_additional"]])
                else:
                    lines.append("  (none)")
                pretty = "\n".join(lines)
                return {"status": pretty, "paths": data}
            if action == "load" and len(args) > 1:
                file_path = args[1]
                if not hasattr(self.core, 'conversation_manager') or \
                   not hasattr(self.core.conversation_manager, 'load_context_file'):
                    return {"error": "Context loading function not available in ConversationManager."}
                success = self.core.conversation_manager.load_context_file(file_path)
                if success:
                    self.update_token_display()
                    return {"status": f"Loaded context file: {file_path}"}
                return {"error": f"Failed to load context file: {file_path}"}

            # New operations: add|write|edit|remove|note with flags
            from penguin.config import WORKSPACE_PATH, load_config
            from penguin.utils.path_utils import enforce_allowed_path

            cfg = load_config()
            scratch_rel = cfg.get('context', {}).get('scratchpad_dir', 'context')
            workspace_context_dir = Path(WORKSPACE_PATH) / scratch_rel
            workspace_context_dir.mkdir(parents=True, exist_ok=True)

            if action == "add" and len(args) >= 2:
                # /context add <path|glob> [--project|--workspace] [--as <name>]
                src = args[1]
                as_name = None
                root_pref = 'project'
                i = 2
                while i < len(args):
                    tok = args[i]
                    if tok == "--workspace":
                        root_pref = 'workspace'
                        i += 1
                        continue
                    if tok == "--project":
                        root_pref = 'project'
                        i += 1
                        continue
                    if tok == "--as" and i + 1 < len(args):
                        as_name = args[i + 1]
                        i += 2
                        continue
                    i += 1

                # Resolve source(s)
                src_path = Path(src)
                if not src_path.is_absolute():
                    # Try treating as project-relative by default
                    # Guard path according to root
                    src_path = enforce_allowed_path(src_path, root_pref=root_pref)

                matches = []
                if any(ch in str(src_path) for ch in ['*', '?', '[']):
                    matches = list(src_path.parent.glob(src_path.name))
                else:
                    matches = [src_path]
                if not matches:
                    return {"error": f"No files matched: {src}"}

                copied = []
                for m in matches:
                    if not m.exists() or not m.is_file():
                        continue
                    dest_name = as_name or m.name
                    dest = workspace_context_dir / dest_name
                    shutil.copy2(m, dest)
                    copied.append(str(dest))
                return {"status": "ok", "copied": copied}

            if action == "write" and len(args) >= 2:
                # /context write <relpath> --body "text"
                rel = args[1]
                body = None
                i = 2
                while i < len(args):
                    tok = args[i]
                    if tok == "--body" and i + 1 < len(args):
                        body = args[i + 1]
                        i += 2
                        continue
                    i += 1
                if body is None:
                    return {"error": "Missing --body <text>"}
                # If env override requests workspace root, honor it for headless CLI parity tests
                root_pref = os.environ.get('PENGUIN_WRITE_ROOT', '').lower()
                if root_pref == 'workspace':
                    base_dir = Path(WORKSPACE_PATH)
                else:
                    base_dir = workspace_context_dir
                dest = base_dir / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(body, encoding='utf-8')
                return {"status": "ok", "written": str(dest)}

            if action == "edit" and len(args) >= 2:
                # /context edit <relpath> --replace A --with B
                rel = args[1]
                repl_from = repl_to = None
                i = 2
                while i < len(args):
                    tok = args[i]
                    if tok == "--replace" and i + 1 < len(args):
                        repl_from = args[i + 1]
                        i += 2
                        continue
                    if tok == "--with" and i + 1 < len(args):
                        repl_to = args[i + 1]
                        i += 2
                        continue
                    i += 1
                if repl_from is None or repl_to is None:
                    return {"error": "Missing --replace and/or --with"}
                dest = workspace_context_dir / rel
                if not dest.exists():
                    return {"error": f"File does not exist: {dest}"}
                content = dest.read_text(encoding='utf-8')
                content = content.replace(repl_from, repl_to)
                dest.write_text(content, encoding='utf-8')
                return {"status": "ok", "edited": str(dest)}

            if action == "remove" and len(args) >= 2:
                # /context remove <relpath>
                rel = args[1]
                dest = workspace_context_dir / rel
                if not dest.exists():
                    return {"error": f"File does not exist: {dest}"}
                dest.unlink()
                return {"status": "ok", "removed": str(dest)}

            if action == "note" and len(args) >= 2:
                # /context note "Title" --body "text"
                title = args[1].strip().replace('/', '-').replace('..', '')
                body = None
                i = 2
                while i < len(args):
                    tok = args[i]
                    if tok == "--body" and i + 1 < len(args):
                        body = args[i + 1]
                        i += 2
                        continue
                    i += 1
                if body is None:
                    return {"error": "Missing --body <text>"}
                notes_dir = workspace_context_dir / 'notes'
                notes_dir.mkdir(parents=True, exist_ok=True)
                filename = f"{title}.md"
                dest = notes_dir / filename
                dest.write_text(body, encoding='utf-8')
                return {"status": "ok", "note": str(dest)}

            return {"error": f"Unknown context command: {action}"}
        except Exception as e:
            return {"error": f"Context command failed: {str(e)}"}
    
    async def _handle_model_command(self, args: List[str]) -> Dict[str, Any]:
        """Handles /model set command for manual model setting"""
        if not args or args[0].lower() != "set":
            return {"error": "Usage: /model set <model_id>"}

        if len(args) < 2:
            return {"error": "Missing model ID. Usage: /model set <model_id>"}
            
        model_id_to_set = args[1]
        success = await self.core.load_model(model_id_to_set)
        if success:
            new_model_name = "Unknown"
            if self.core.model_config and self.core.model_config.model:
                new_model_name = self.core.model_config.model
            # Update token display as max_tokens might change
            self.update_token_display() 
            return {"status": f"Successfully set model to: {new_model_name}", "new_model_name": new_model_name}
        else:
            return {"error": f"Failed to set model to: {model_id_to_set}"}

    async def _handle_stream_command(self, args: List[str]) -> Dict[str, Any]:
        """Handle streaming mode toggles and status checks"""
        # Get current streaming status
        streaming_enabled = self.get_streaming_status()
        
        # Check if streaming is configured/available
        if streaming_enabled is None:
            return {"error": "Streaming configuration not available with current model"}
        
        if not args:
            # Get additional stream status info
            stream_status = "No active stream"
            if hasattr(self.core, 'current_stream'):
                if self.core.current_stream is not None:
                    stream_status = "active" if not self.core.current_stream.done() else "completed"
            
            model_name = None
            if hasattr(self.core, 'model_config') and hasattr(self.core.model_config, 'model'):
                model_name = self.core.model_config.model
            elif hasattr(self.core, 'config') and hasattr(self.core.config, 'model_config'):
                if hasattr(self.core.config.model_config, 'model'):
                    model_name = self.core.config.model_config.model
                
            return {
                "status": f"Streaming is currently {'enabled' if streaming_enabled else 'disabled'}",
                "details": {
                    "enabled": streaming_enabled,
                    "current_stream": stream_status,
                    "model": model_name
                }
            }
            
        action = args[0].lower()
        if action in ["on", "enable", "true", "1"]:
            success = self.set_streaming(True)
            return {"status": "Streaming enabled" if success else "Failed to enable streaming"}
        elif action in ["off", "disable", "false", "0"]:
            success = self.set_streaming(False)
            return {"status": "Streaming disabled" if success else "Failed to disable streaming"}
        
        return {"error": f"Unknown streaming command: {action}"}
    
    def set_streaming(self, enabled: bool = True) -> bool:
        """
        Enable or disable streaming mode
        
        This synchronizes the streaming settings between:
        1. core.model_config.streaming_enabled
        2. core.api_client streaming settings (if available)
        
        Returns:
            True if successful, False otherwise
        """
        success = False
        
        # Direct model_config attribute
        if hasattr(self.core, 'model_config') and hasattr(self.core.model_config, 'streaming_enabled'):
            self.core.model_config.streaming_enabled = enabled
            success = True
            
        # Config with model_config attribute 
        elif hasattr(self.core, 'config') and hasattr(self.core.config, 'model_config'):
            if hasattr(self.core.config.model_config, 'streaming_enabled'):
                self.core.config.model_config.streaming_enabled = enabled
                success = True
                
        # Config with model property/attribute that has streaming_enabled
        elif hasattr(self.core, 'config') and hasattr(self.core.config, 'model'):
            model_attr = getattr(self.core.config, 'model')
            if isinstance(model_attr, dict) and 'streaming_enabled' in model_attr:
                model_attr['streaming_enabled'] = enabled
                success = True
        
        # Also update API client if it has a set_streaming method
        if hasattr(self.core, 'api_client') and hasattr(self.core.api_client, 'set_streaming'):
            try:
                self.core.api_client.set_streaming(enabled)
                success = True
            except Exception as e:
                print(f"[Interface] Error updating API client streaming setting: {e}")
        
        return success
    
    def get_streaming_status(self) -> Optional[bool]:
        """Get current streaming mode setting from ModelConfig"""
        # Direct model_config attribute
        if hasattr(self.core, 'model_config') and self.core.model_config is not None and \
           hasattr(self.core.model_config, 'streaming_enabled'):
            return self.core.model_config.streaming_enabled
        
        # Fallback for older config structure if model_config is not primary
        # This part might become less relevant if ModelConfig is always the source of truth
        if hasattr(self.core, 'config') and self.core.config is not None:
            if hasattr(self.core.config, 'model_config') and self.core.config.model_config is not None and \
               hasattr(self.core.config.model_config, 'streaming_enabled'):
                return self.core.config.model_config.streaming_enabled
            
            if hasattr(self.core.config, 'model') and isinstance(self.core.config.model, dict) and \
               'streaming_enabled' in self.core.config.model:
                return self.core.config.model.get('streaming_enabled')
                
        print("[Interface] Warning: Could not determine streaming status from core.model_config or core.config.")
        return None # Indicate undetermined status
    
    def _get_command_suggestions(self) -> List[str]:
        """Get valid command list"""
        return [
            "/chat [list|load|summary]",
            "/task [create|run|status]",
            "/project [create|run|status]",
            "/run [--247] [--time MINUTES]",
            "/stream [on|off] - Toggle streaming mode (on by default)",
            "/help - Show this help message",
            "/exit - Exit the program",
            "/tokens [reset|detail] - Show or reset token usage",
            "/context [list|load FILE] - Manage context files",
            "/list - Show projects and tasks",
            "/debug [tokens] - Run debug functions",
            "/models - Interactive model selection (autocomplete search)",
            "/model set <id> - Manually set a specific model ID"
        ]
        
    def is_active(self) -> bool:
        """Check if interface is active"""
        return self._active

    async def _handle_debug_command(self, args: List[str]) -> Dict[str, Any]:
        """Handle debug commands for development purposes"""
        if not args:
            return {"error": "Missing debug subcommand"}
        
        subcmd = args[0].lower()
        if subcmd == "tokens":
            # Notify token usage
            if hasattr(self.core, '_notify_token_usage'):
                self.core._notify_token_usage()
                return {"status": "Debug: Notified token usage based on conversation system data."}
            return {"status": "Debug: Token notification function not available"}
        elif subcmd == "stream":
            # Stream related debugging – always set default first to avoid UnboundLocalError.
            stream_status = "inactive"
            if hasattr(self.core, 'current_stream') and self.core.current_stream is not None:
                if hasattr(self.core.current_stream, 'done') and callable(self.core.current_stream.done):
                    stream_status = "active" if not self.core.current_stream.done() else "completed"
                else:
                    stream_status = "unknown (current_stream has no 'done' method)"
            return {"status": f"Debug: Stream status is {stream_status}"}
        elif subcmd == "sample":
            demo_content = (
                "<details>\n"
                "<summary>🧠  Click to show / hide internal reasoning</summary>\n\n"
                "### Internal reasoning (collapsible)\n\n"
                "1. Parse the user's request\n"
                "2. Decide on tone → friendly but direct\n"
                "3. Build a short factual statement\n"
                "4. Offer next actionable step\n\n"
                "> _Note: this section is hidden by default – press ENTER to expand / collapse in the TUI._\n\n"
                "</details>\n\n"
                "---\n\n"
                "### Final answer (always visible)\n\n"
                "This is a demo assistant reply rendered by `/debug sample`.\n"
                "Use it to verify that collapsible reasoning works correctly in the UI."
            )

            try:
                # Add to conversation history
                if hasattr(self.core, 'conversation_manager'):
                    self.core.conversation_manager.conversation.add_message(
                        role="assistant",
                        content=demo_content,
                        category=MessageCategory.DIALOG,
                        metadata={"demo": True}
                    )

                # Emit UI event so it shows up immediately
                await self.core.emit_ui_event("message", {
                    "role": "assistant",
                    "content": demo_content,
                    "category": MessageCategory.DIALOG,
                    "metadata": {"demo": True}
                })

                return {"status": "Injected demo collapsible message."}
            except Exception as e:
                return {"error": f"Failed to inject demo message: {e}"}
        return {"error": f"Unknown debug command: {subcmd}"}

    def _initialize_streaming_settings(self) -> None:
        """
        Initializes streaming settings based on core.model_config.
        Ensures that core.model_config.streaming_enabled is the source of truth.
        If it's not set, it might default to True based on config.yml structure if appropriate.
        """
        # Primary source of truth should be core.model_config
        if hasattr(self.core, 'model_config') and self.core.model_config is not None:
            if not hasattr(self.core.model_config, 'streaming_enabled') or self.core.model_config.streaming_enabled is None:
                # If not set on model_config, check config.yml default
                default_streaming_enabled = True # Default to True if not specified elsewhere
                if hasattr(self.core, 'config') and self.core.config is not None and \
                   hasattr(self.core.config, 'model') and isinstance(self.core.config.model, dict):
                    default_streaming_enabled = self.core.config.model.get('streaming_enabled', True)
                
                self.core.model_config.streaming_enabled = default_streaming_enabled
                print(f"[Interface] Initialized core.model_config.streaming_enabled to {self.core.model_config.streaming_enabled}")
            # If it is set, we respect it.
        else:
            print("[Interface] Warning: core.model_config not available during streaming initialization.")

        # Optionally, ensure API client is also synced if possible, though this is more for `set_streaming`
        if hasattr(self.core, 'api_client') and hasattr(self.core.api_client, 'set_streaming'):
            current_status = self.get_streaming_status()
            if current_status is not None:
                try:
                    self.core.api_client.set_streaming(current_status)
                except Exception as e:
                    print(f"[Interface] Warning: Error syncing API client streaming status on init: {e}")

    async def list_available_models(self) -> List[Dict[str, Any]]:
        """
        List available models for the UI to display.
        If client_preference is 'openrouter', fetches models from OpenRouter API.
        Otherwise, attempts to get models from core config or provides defaults.
        
        Returns:
            List of model dictionaries with metadata
        """
        current_model_name_from_core = None
        current_provider_from_core = None # This might be tricky with OpenRouter, as OR is the provider
        client_preference = "litellm" # Default

        if hasattr(self.core, 'model_config') and self.core.model_config is not None:
            current_model_name_from_core = getattr(self.core.model_config, 'model', None)
            # For OpenRouter, self.core.model_config.provider might be 'openrouter'
            # but the actual underlying model provider is part of the model ID (e.g., openai/gpt-4o)
            current_provider_from_core = getattr(self.core.model_config, 'provider', None)
            client_preference = getattr(self.core.model_config, 'client_preference', 'litellm')

        if client_preference == 'openrouter':
            try:
                async with httpx.AsyncClient() as client:
                    response = await client.get("https://openrouter.ai/api/v1/models")
                    response.raise_for_status() # Raise an exception for HTTP errors 4xx/5xx
                    openrouter_models = response.json().get("data", [])
                
                available_models = []
                for or_model in openrouter_models:
                    model_id = or_model.get("id")
                    # Determine if this is the current model
                    # For OpenRouter, the model_id from their API is what we store in our config as `model`
                    is_current = (model_id == current_model_name_from_core)
                    
                    # Extract provider from ID if possible (e.g. "openai/gpt-4o" -> "openai")
                    # This is a heuristic and might need refinement based on OpenRouter's ID structure
                    underlying_provider = model_id.split('/')[0] if '/' in model_id else "openrouter"

                    available_models.append({
                        "id": model_id, # This is the ID to use for /model set
                        "name": or_model.get("name", model_id), 
                        "provider": underlying_provider, # The conceptual provider
                        "client_preference": "openrouter", # Explicitly state it
                        "vision_enabled": "image" in or_model.get("architecture", {}).get("input_modalities", []),
                        "max_tokens": or_model.get("context_length"), # OpenRouter calls it context_length
                        "temperature": None, # OpenRouter doesn't list default temp per model here
                        "current": is_current
                    })
                
                # Sort to bring current model to top, then by ID
                available_models.sort(key=lambda m: (not m["current"], m["id"]))
                return available_models
            except httpx.RequestError as e:
                print(f"[Interface] Error fetching models from OpenRouter: {e}. Falling back to config.yml.")
            except Exception as e:
                print(f"[Interface] Unexpected error processing OpenRouter models: {e}. Falling back to config.yml.")

        # Fallback to previous logic (config.yml or core.list_available_models) if not OpenRouter or if API fails
        if hasattr(self.core, 'list_available_models') and callable(self.core.list_available_models) and client_preference != 'openrouter':
            try:
                # This assumes core.list_available_models() does NOT call this interface method again
                return self.core.list_available_models() 
            except Exception as e:
                print(f"[Interface] Error listing models from core: {e}")
        
        # Fallback to parsing config.yml via self.core.config
        available_models_from_config = []
        if hasattr(self.core, 'config') and self.core.config is not None and \
           hasattr(self.core.config, 'model_configs') and isinstance(self.core.config.model_configs, dict):
            for model_key, conf in self.core.config.model_configs.items():
                if isinstance(conf, dict):
                    # Determine if current model based on matching model_key with current_model_name_from_core
                    # (if client_preference for the current model is also from config)
                    is_config_entry_current = (model_key == current_model_name_from_core)

                    model_entry = {
                        "id": model_key, 
                        "name": conf.get("model", model_key),
                        "provider": conf.get("provider", "unknown"),
                        "client_preference": conf.get("client_preference", "litellm"),
                        "vision_enabled": conf.get("vision_enabled", False),
                        "max_tokens": conf.get("max_tokens"),
                        "temperature": conf.get("temperature"),
                        "current": is_config_entry_current
                    }
                    available_models_from_config.append(model_entry)
        
        if available_models_from_config:
            available_models_from_config.sort(key=lambda m: (not m["current"], m["id"]))
            return available_models_from_config

        # Final fallback to hardcoded defaults if all else fails
        print("[Interface] Warning: Falling back to hardcoded default models list.")
        hardcoded_models = [
            { "id": "anthropic/claude-3-5-sonnet-20240620", "name": "claude-3-5-sonnet-20240620", "provider": "anthropic", "current": (current_model_name_from_core == "anthropic/claude-3-5-sonnet-20240620") },
            { "id": "openai/gpt-4o", "name": "gpt-4o", "provider": "openai", "current": (current_model_name_from_core == "openai/gpt-4o") },
        ]
        hardcoded_models.sort(key=lambda m: (not m["current"], m["id"]))
        return hardcoded_models

    async def load_model(self, model_id_from_config: str) -> bool:
        """
        Load a model by name.
        Attempts to call load_model on core if available.
        
        Args:
            model_name: Name of the model to load (this should be the key from `model_configs` in `config.yml`)
            
        Returns:
            True if successful, False otherwise
        """
        if hasattr(self.core, 'load_model') and callable(self.core.load_model):
            try:
                # Now call the async core method
                return await self.core.load_model(model_id_from_config) 
            except Exception as e:
                print(f"[Interface] Error loading model via core.load_model: {e}\\n{traceback.format_exc()}")
                return False
        
        # Fallback if core doesn't have the method - attempt to reconfigure model_config
        # This is a simplified approach and might not re-initialize APIClient correctly.
        print(f"[Interface] Warning: core.load_model not found. Attempting fallback reconfiguration of core.model_config.")
        try:
            if not (hasattr(self.core, 'config') and self.core.config is not None and \
                    hasattr(self.core.config, 'model_configs') and isinstance(self.core.config.model_configs, dict)):
                print("[Interface] Error: Cannot load model. core.config.model_configs not available.")
                return False

            new_model_conf_dict = self.core.config.model_configs.get(model_id_from_config)
            if not isinstance(new_model_conf_dict, dict):
                print(f"[Interface] Error: Model ID '{model_id_from_config}' not found in core.config.model_configs.")
                return False

            if hasattr(self.core, 'model_config') and self.core.model_config is not None:
                # Update attributes of the existing ModelConfig instance
                self.core.model_config.model = new_model_conf_dict.get("model", model_id_from_config)
                self.core.model_config.provider = new_model_conf_dict.get("provider")
                self.core.model_config.client_preference = new_model_conf_dict.get("client_preference")
                self.core.model_config.api_base = new_model_conf_dict.get("api_base") # For Ollama etc.
                self.core.model_config.streaming_enabled = new_model_conf_dict.get("streaming_enabled", self.core.model_config.streaming_enabled)
                self.core.model_config.vision_enabled = new_model_conf_dict.get("vision_enabled", self.core.model_config.vision_enabled)
                self.core.model_config.max_tokens = new_model_conf_dict.get("max_tokens", self.core.model_config.max_tokens)
                self.core.model_config.temperature = new_model_conf_dict.get("temperature", self.core.model_config.temperature)
                # Potentially need to re-initialize or update APIClient here
                # self.core.api_client.reconfigure(self.core.model_config) # If such a method exists
                print(f"[Interface] Fallback: Updated core.model_config for model '{model_id_from_config}'. APIClient may need manual re-initialization in PenguinCore.")
                # After changing model, streaming settings might change, so re-initialize/sync them
                self._initialize_streaming_settings()
                # Also update token display as max_tokens might have changed
                self.update_token_display()
                return True
            else:
                print("[Interface] Error: core.model_config not available for fallback update.")
                return False
        except Exception as e:
            print(f"[Interface] Error in fallback model loading: {e}\\n{traceback.format_exc()}")
            return False

    async def _handle_models_command(self, args: List[str]) -> Dict[str, Any]:
        """Handle /models command - launches interactive model selector"""
        try:
            from penguin.cli.model_selector import interactive_model_selector
            
            # Get current model for display
            current_model_name = None
            if self.core.model_config and self.core.model_config.model:
                current_model_name = self.core.model_config.model
            
            # Run the interactive selector
            selected_model = await interactive_model_selector(current_model_name)
            
            if selected_model:
                # Load the selected model
                success = await self.core.load_model(selected_model)
                if success:
                    # Update token display as max_tokens might change
                    self.update_token_display()
                    return {
                        "status": f"Successfully selected model: {selected_model}",
                        "model_id": selected_model,
                        "success": True
                    }
                else:
                    return {"error": f"Failed to load selected model: {selected_model}"}
            else:
                return {"status": "Model selection cancelled"}
                
        except ImportError:
            return {"error": "Model selector not available. Use '/model set <id>' instead."}
        except Exception as e:
            return {"error": f"Error in model selection: {str(e)}"}