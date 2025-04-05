import asyncio
import traceback
from datetime import datetime
from typing import Any, Dict, List, Optional, Callable, Tuple
from pathlib import Path

from rich.console import Console # type: ignore

from penguin.core import PenguinCore
from penguin.system.state import parse_iso_datetime
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
        self._progress_callbacks = []
        self._token_callbacks = []
        
        # Initialize with safe defaults
        try:
            # Enable streaming by default with enhanced compatibility
            self._enable_streaming_by_default()
            
            # Register for progress updates from core
            if hasattr(self.core, 'register_progress_callback'):
                self.core.register_progress_callback(self._on_progress_update)
            
            # Register for token updates from core
            if hasattr(self.core, 'register_token_callback'):
                self.core.register_token_callback(self._on_token_update)
            
            # Initial token update
            self.update_token_display()
        except Exception as e:
            print(f"[Interface] Warning: Error during initialization: {e}")
            # Continue despite errors - we want the interface to be as resilient as possible

    def register_progress_callback(self, callback: Callable[[int, int, Optional[str]], None]) -> None:
        """Register callback for progress updates"""
        self._progress_callbacks.append(callback)
        
    def register_token_callback(self, callback: Callable[[Dict[str, int]], None]) -> None:
        """Register callback for token usage updates"""
        print(f"[Interface] Registering token callback: {callback.__qualname__ if hasattr(callback, '__qualname__') else callback}")
        self._token_callbacks.append(callback)
        
    def _on_progress_update(self, iteration: int, max_iterations: int, message: Optional[str] = None) -> None:
        """Handle progress updates from core and forward to UI"""
        for callback in self._progress_callbacks:
            callback(iteration, max_iterations, message)
            
    def _on_token_update(self, usage: Dict[str, Any]) -> None:
        """Handle token updates from core and forward to UI"""
        # Transform token usage from conversation system format to UI format if needed
        transformed_usage = {
            "prompt": usage.get("prompt_tokens", 0),
            "completion": usage.get("completion_tokens", 0),
            "total": usage.get("total_tokens", 0),
            "max_tokens": usage.get("max_tokens", 200000)
        }
        
        # Forward the token usage to UI callbacks
        for callback in self._token_callbacks:
            try:
                callback(transformed_usage)
            except Exception as e:
                print(f"[Interface] Error in token callback: {e}")
            
    def get_token_usage(self) -> Dict[str, int]:
        """Get current token usage statistics from conversation manager"""
        try:
            # Check if conversation_manager exists
            if not hasattr(self.core, 'conversation_manager'):
                return {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "max_tokens": 200000}
                
            usage = self.core.conversation_manager.get_token_usage()
            
            # Handle both dictionary formats from different implementations
            if isinstance(usage, dict):
                # If it's already in the right format with prompt_tokens, etc.
                if "prompt_tokens" in usage:
                    return usage
                
                # If it's in the form {"total": X} convert to the expected format
                if "total" in usage:
                    return {
                        "prompt_tokens": usage.get("total", 0),
                        "completion_tokens": 0,
                        "total_tokens": usage.get("total", 0),
                        "max_tokens": usage.get("max_tokens", 200000)
                    }
            
            # Default empty format
            return {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "max_tokens": 200000}
        except Exception as e:
            print(f"Error getting token usage: {e}")
            return {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "max_tokens": 200000}
        
    def update_token_display(self) -> None:
        """Update token usage display"""
        usage = self.get_token_usage()
        for callback in self._token_callbacks:
            callback(usage)
            
    async def process_input(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Main processing entry point"""
        try:
            # Extract streaming flag, default to current model config if not specified
            streaming = None
            if isinstance(input_data, dict) and 'streaming' in input_data:
                streaming = input_data.pop('streaming')
            
            # Check for command
            if "text" in input_data and input_data["text"].startswith("/"):
                return await self.handle_command(input_data["text"][1:])
                
            # Process regular message with streaming based on configuration
            # Pass streaming flag to core.process as an optional override
            response = await self.core.process(input_data, streaming=streaming)
            
            # Update token usage after processing
            self.update_token_display()
            self.message_count += 1
            
            return response
        except Exception as e:
            return self._format_error(e)

    async def handle_command(self, command: str) -> Dict[str, Any]:
        """Handle slash commands"""
        parts = command.split(" ", 2)
        cmd, args = parts[0].lower(), parts[1:] if len(parts) > 1 else []

        handlers = {
            "chat": self._handle_chat_command,
            "task": self._handle_task_command,
            "project": self._handle_project_command,
            "run": self._handle_run_command,
            "image": self._handle_image_command,
            "list": self._handle_list_command,
            "help": self._handle_help_command,
            "exit": self._handle_exit_command,
            "tokens": self._handle_tokens_command,
            "context": self._handle_context_command,
            "debug": self._handle_debug_command,
            "stream": self._handle_stream_command,  # Added stream command handler
        }
        
        handler = handlers.get(cmd, self._invalid_command)
        result = await handler(args)
        
        # Update token display after command execution
        self.update_token_display()
        
        return result

    async def _handle_chat_command(self, args: List[str]) -> Dict[str, Any]:
        """Handle conversation management commands"""
        if not args:
            return {"error": "Missing chat subcommand"}
            
        subcmd = args[0].lower()
        if subcmd == "list":
            conversations = self.core.list_conversations()
            # Convert to ConversationSummary objects for display
            summaries = []
            for conv in conversations:
                # Extract data from the conversation dictionary
                session_id = conv.get("id", "unknown")
                title = conv.get("title", "Untitled Conversation")
                message_count = conv.get("message_count", 0)
                last_active = conv.get("last_active", datetime.now().isoformat())
                
                # Create ConversationSummary object
                summary = ConversationSummary(
                    session_id=session_id,
                    title=title,
                    message_count=message_count,
                    last_active=last_active
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
        if action == "create" and len(args) > 2:
            return self.core.project_manager.create_task(args[1], args[2])
        elif action == "run" and len(args) > 1:
            return await self.core.start_run_mode(args[1], " ".join(args[2:]))
        elif action == "status" and len(args) > 1:
            return self.core.project_manager.get_task_status(args[1])
        return {"error": f"Unknown task command: {action}"}

    async def _handle_project_command(self, args: List[str]) -> Dict[str, Any]:
        """Handle project management commands"""
        if not args:
            return {"error": "Missing project subcommand"}
            
        action = args[0].lower()
        if action == "create" and len(args) > 2:
            return self.core.project_manager.create_project(args[1], args[2])
        elif action == "run" and len(args) > 1:
            return await self.core.start_run_mode(args[1], " ".join(args[2:]), mode_type="project")
        elif action == "status" and len(args) > 1:
            return self.core.project_manager.get_project_status(args[1])
        return {"error": f"Unknown project command: {action}"}

    async def _handle_image_command(self, args: List[str]) -> Dict[str, Any]:
        """Handle image processing command"""
        return await self.core.process({
            "text": " ".join(args[1:]) if len(args) > 1 else "",
            "image_path": args[0] if args else ""
        })

    async def _handle_run_command(self, args: List[str]) -> Dict[str, Any]:
        """Handle run mode activation"""
        continuous = "--247" in args
        time_limit = next((int(args[i+1]) for i, a in enumerate(args) if a == "--time"), None)
        
        if continuous:
            # Use core's run mode instead of creating a new one
            return await self.core.start_run_mode(
                name=None, 
                description=None, 
                continuous=True, 
                time_limit=time_limit
            )
        elif args:
            return await self.core.start_run_mode(args[0], " ".join(args[1:]))
        return {"error": "Invalid run command"}

    async def _handle_list_command(self, args: List[str]) -> Dict[str, Any]:
        """Handle list command"""
        return self.core.project_manager.process_list_command()

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

    def _invalid_command(self, args: List[str]) -> Dict[str, Any]:
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
        
    def get_detailed_token_usage(self) -> Dict[str, Any]:
        """Get detailed token usage statistics by category from the conversation system"""
        if not hasattr(self.core, 'conversation_manager'):
            return {"error": "Conversation manager not available"}
        
        try:
            # Get basic token usage first
            basic_usage = self.get_token_usage()
            
            # Prepare result with basics
            result = {
                "total": self.core.total_tokens_used,
                "max_tokens": basic_usage.get("max_tokens", 200000),
                "prompt_tokens": basic_usage.get("prompt_tokens", 0),
                "completion_tokens": basic_usage.get("completion_tokens", 0),
                "total_tokens": basic_usage.get("total_tokens", 0),
                "categories": {},
                "raw_counts": {}
            }
            
            # Try to get allocations if conversation has the method
            if hasattr(self.core.conversation_manager.conversation, "get_current_allocations"):
                try:
                    allocations = self.core.conversation_manager.conversation.get_current_allocations()
                    result["categories"] = {str(category.name): value for category, value in allocations.items()}
                except Exception as e:
                    print(f"Error getting allocations: {e}")
            
            # Try to get raw counts if _token_budgets exists
            if hasattr(self.core.conversation_manager.conversation, "_token_budgets"):
                for category, budget in self.core.conversation_manager.conversation._token_budgets.items():
                    result["raw_counts"][str(category.name)] = budget.current_tokens
            
            return result
        except Exception as e:
            return {"error": f"Error getting token allocations: {str(e)}"}

    async def _handle_tokens_command(self, args: List[str]) -> Dict[str, Any]:
        """Handle tokens command to show or reset token usage"""
        if args and args[0].lower() == "reset":
            # Reset token counters if available
            if hasattr(self.core.conversation_manager.conversation, "reset_token_budgets"):
                self.core.conversation_manager.conversation.reset_token_budgets()
                return {"status": "Token counters reset"}
            return {"status": "Token reset not implemented in this version"}
        elif args and args[0].lower() == "detail":
            # Show detailed token usage by category
            return {"token_usage_detailed": self.get_detailed_token_usage()}
        else:
            # Show standard token usage
            return {"token_usage": self.get_token_usage()}
            
    async def _handle_context_command(self, args: List[str]) -> Dict[str, Any]:
        """Handle context file commands"""
        if not args:
            # List available context files
            return {"context_files": self.core.list_context_files()}
            
        action = args[0].lower()
        if action == "list":
            return {"context_files": self.core.list_context_files()}
        elif action == "load" and len(args) > 1:
            file_path = args[1]
            success = self.core.conversation_manager.load_context_file(file_path)
            if success:
                return {"status": f"Loaded context file: {file_path}"}
            else:
                return {"error": f"Failed to load context file: {file_path}"}
        
        return {"error": f"Unknown context command: {action}"}
    
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
        """Get current streaming mode setting"""
        # Direct model_config attribute
        if hasattr(self.core, 'model_config') and hasattr(self.core.model_config, 'streaming_enabled'):
            return self.core.model_config.streaming_enabled
            
        # Config with model_config attribute
        elif hasattr(self.core, 'config') and hasattr(self.core.config, 'model_config'):
            if hasattr(self.core.config.model_config, 'streaming_enabled'):
                return self.core.config.model_config.streaming_enabled
                
        # Config with model property/attribute that has streaming_enabled
        elif hasattr(self.core, 'config') and hasattr(self.core.config, 'model'):
            model_attr = getattr(self.core.config, 'model')
            if isinstance(model_attr, dict) and 'streaming_enabled' in model_attr:
                return model_attr['streaming_enabled']
                
        return None
    
    def _get_command_suggestions(self) -> List[str]:
        """Get valid command list"""
        return [
            "/chat [list|load|summary]",
            "/task [create|run|status]",
            "/project [create|run|status]",
            "/run [--247] [--time MINUTES]",
            "/image [PATH]",
            "/stream [on|off] - Toggle streaming mode (on by default)",
            "/help - Show this help message",
            "/exit - Exit the program",
            "/tokens [reset|detail] - Show or reset token usage",
            "/context [list|load FILE] - Manage context files",
            "/list - Show projects and tasks",
            "/debug [tokens] - Run debug functions"
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
            # Stream related debugging
            if hasattr(self.core, 'current_stream'):
                stream_status = "active" if self.core.current_stream and not self.core.current_stream.done() else "inactive"
                return {"status": f"Debug: Stream status is {stream_status}"}
            return {"status": "Debug: Stream functionality not available"}
        return {"error": f"Unknown debug command: {subcmd}"}

    def _enable_streaming_by_default(self) -> None:
        """Enable streaming by default, with compatibility for both config types"""
        # Direct model_config attribute
        if hasattr(self.core, 'model_config') and hasattr(self.core.model_config, 'streaming_enabled'):
            self.core.model_config.streaming_enabled = True
            
        # Config with model_config attribute
        elif hasattr(self.core, 'config') and hasattr(self.core.config, 'model_config'):
            if hasattr(self.core.config.model_config, 'streaming_enabled'):
                self.core.config.model_config.streaming_enabled = True
                
        # Config with model property/attribute that has streaming_enabled
        elif hasattr(self.core, 'config') and hasattr(self.core.config, 'model'):
            model_attr = getattr(self.core.config, 'model')
            if isinstance(model_attr, dict) and 'streaming_enabled' in model_attr:
                model_attr['streaming_enabled'] = True

    def list_available_models(self) -> List[Dict[str, Any]]:
        """
        List available models for the UI to display.
        Attempts to get models from core if available, otherwise provides defaults.
        
        Returns:
            List of model dictionaries with metadata
        """
        # Try to get from core if it has the method
        if hasattr(self.core, 'list_available_models'):
            try:
                return self.core.list_available_models()
            except Exception as e:
                print(f"[Interface] Error listing models from core: {e}")
        
        # Fallback to default models
        default_models = [
            {
                "name": "claude-3-5-sonnet-20240620",
                "provider": "anthropic",
                "client_preference": "litellm",
                "vision_enabled": True
            },
            {
                "name": "gpt-4o",
                "provider": "openai",
                "client_preference": "litellm", 
                "vision_enabled": True
            },
            {
                "name": "gemini-1.5-pro",
                "provider": "google",
                "client_preference": "litellm",
                "vision_enabled": True
            }
        ]
        
        # If core has model_config, add the current model to the top of the list
        if hasattr(self.core, 'model_config'):
            try:
                model_name = getattr(self.core.model_config, 'model', None)
                provider = getattr(self.core.model_config, 'provider', 'unknown')
                if model_name:
                    current_model = {
                        "name": model_name,
                        "provider": provider,
                        "client_preference": getattr(self.core.model_config, 'client_preference', 'litellm'),
                        "vision_enabled": getattr(self.core.model_config, 'vision_enabled', False),
                        "current": True
                    }
                    # Add to front of list
                    default_models.insert(0, current_model)
            except Exception as e:
                print(f"[Interface] Error adding current model to list: {e}")
                
        return default_models
        
    def load_model(self, model_name: str) -> bool:
        """
        Load a model by name.
        Attempts to call load_model on core if available.
        
        Args:
            model_name: Name of the model to load
            
        Returns:
            True if successful, False otherwise
        """
        if hasattr(self.core, 'load_model'):
            try:
                return self.core.load_model(model_name)
            except Exception as e:
                print(f"[Interface] Error loading model via core: {e}")
                return False
        
        # Fallback if core doesn't have the method - just update model info if possible
        try:
            if hasattr(self.core, 'model_config'):
                # Parse model parts - format might be provider/model or just model
                if "/" in model_name:
                    provider, model = model_name.split("/", 1)
                    self.core.model_config.provider = provider
                    self.core.model_config.model = model
                else:
                    self.core.model_config.model = model_name
                return True
            return False
        except Exception as e:
            print(f"[Interface] Error in fallback model loading: {e}")
            return False