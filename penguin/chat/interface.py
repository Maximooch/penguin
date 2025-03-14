import asyncio
import traceback
from datetime import datetime
from typing import Any, Dict, List, Optional, Callable, Tuple
from pathlib import Path

from rich.console import Console # type: ignore

from penguin.core import PenguinCore
from penguin.system.conversation import parse_iso_datetime
from penguin.system.conversation_menu import ConversationSummary, ConversationMenu

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
        
        # Register for progress updates from core
        self.core.register_progress_callback(self._on_progress_update)
        
        # Register for token updates from core (if available)
        if hasattr(self.core, 'register_token_callback'):
            self.core.register_token_callback(self._on_token_update)
        
        # Initial token update
        self.update_token_display()

    def register_progress_callback(self, callback: Callable[[int, int, Optional[str]], None]) -> None:
        """Register callback for progress updates"""
        self._progress_callbacks.append(callback)
        
    def register_token_callback(self, callback: Callable[[Dict[str, int]], None]) -> None:
        """Register callback for token usage updates"""
        self._token_callbacks.append(callback)
        
    def _on_progress_update(self, iteration: int, max_iterations: int, message: Optional[str] = None) -> None:
        """Handle progress updates from core and forward to UI"""
        for callback in self._progress_callbacks:
            callback(iteration, max_iterations, message)
            
    def _on_token_update(self, usage: Dict[str, int]) -> None:
        """Handle token updates from core and forward to UI"""
        # Update our callbacks with the new usage data
        for callback in self._token_callbacks:
            callback(usage)
            
    def get_token_usage(self) -> Dict[str, int]:
        """Get current token usage statistics"""
        usage = self.core.get_token_usage()
        # Flatten the nested structure for simpler UI display
        result = {
            "prompt": 0,
            "completion": 0,
            "total": self.core.total_tokens_used
        }
        
        # Extract usage from main model
        if "main_model" in usage:
            result["prompt"] = usage["main_model"].get("prompt", 0)
            result["completion"] = usage["main_model"].get("completion", 0)
            
        return result
        
    def update_token_display(self) -> None:
        """Update token usage display"""
        usage = self.get_token_usage()
        for callback in self._token_callbacks:
            callback(usage)
            
    async def process_input(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Main processing entry point"""
        try:
            # Check for command
            if "text" in input_data and input_data["text"].startswith("/"):
                return await self.handle_command(input_data["text"][1:])
                
            # Process regular message
            response = await self.core.process(input_data)
            
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
            conversations = self.core.conversation_system.loader.list_conversations()
            return {"conversations": conversations}
        elif subcmd == "load" and len(args) > 1:
            return await self._load_conversation(args[1])
        elif subcmd == "summary":
            return {"summary": self.core.conversation_system.get_history()}
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
            self.core.conversation_system.load(session_id)
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
        if not hasattr(self.core, 'conversation_system'):
            return {"error": "Conversation system not available"}
        
        try:
            # Get the category allocations from conversation system
            allocations = self.core.conversation_system.get_current_allocations()
            
            # Convert Enum keys to strings for easier display
            result = {
                "categories": {str(category.name): value for category, value in allocations.items()},
                "total": self.core.total_tokens_used,
                "max_tokens": getattr(self.core.conversation_system, "max_tokens", 0)
            }
            
            # Add raw counts where available
            result["raw_counts"] = {}
            for category, budget in self.core.conversation_system._token_budgets.items():
                result["raw_counts"][str(category.name)] = budget.current_tokens
            
            return result
        except Exception as e:
            return {"error": f"Error getting token allocations: {str(e)}"}

    async def _handle_tokens_command(self, args: List[str]) -> Dict[str, Any]:
        """Handle tokens command to show or reset token usage"""
        if args and args[0].lower() == "reset":
            # Reset token counters
            # This would need to be implemented in core.py
            return {"status": "Token counters reset"}
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
            success = self.core.conversation_system.load_context_file(file_path)
            if success:
                return {"status": f"Loaded context file: {file_path}"}
            else:
                return {"error": f"Failed to load context file: {file_path}"}
        
        return {"error": f"Unknown context command: {action}"}
    
    def _get_command_suggestions(self) -> List[str]:
        """Get valid command list"""
        return [
            "/chat [list|load|summary]",
            "/task [create|run|status]",
            "/project [create|run|status]",
            "/run [--247] [--time MINUTES]",
            "/image [PATH]",
            "/help - Show this help message",
            "/exit - Exit the program",
            "/tokens [reset] - Show or reset token usage",
            "/context [list|load FILE] - Manage context files",
            "/list - Show projects and tasks"
        ]
        
    def is_active(self) -> bool:
        """Check if interface is active"""
        return self._active