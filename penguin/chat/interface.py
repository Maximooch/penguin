from typing import Any, Dict, List, Optional
from penguin.core import PenguinCore
from penguin.system.conversation import ConversationSummary
from penguin.system.conversation_menu import ConversationMenu

class PenguinInterface:
    """Handles all CLI business logic and core integration"""
    
    def __init__(self, core: PenguinCore):
        self.core = core
        self.conversation_menu = ConversationMenu()
        self._active = True

    async def process_input(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Main processing entry point"""
        try:
            if "text" in input_data and input_data["text"].startswith("/"):
                return await self.handle_command(input_data["text"][1:])
            return await self.core.process(input_data)
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
            "list": self._handle_list_command
        }
        
        return await handlers.get(cmd, self._invalid_command)(args)

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
            run_mode = RunMode(self.core)
            return await run_mode.start_continuous(time_limit)
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

    def _get_command_suggestions(self) -> List[str]:
        """Get valid command list"""
        return [
            "/chat [list|load|summary]",
            "/task [create|run|status]",
            "/project [create|run|status]",
            "/run [--247] [--time MINUTES]",
            "/image [PATH]"
        ]