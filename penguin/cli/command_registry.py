"""
Command Registry System for Penguin TUI.

Loads and manages commands from commands.yml configuration.
"""

import yaml
import os
from pathlib import Path
from typing import Dict, List, Optional, Any, Callable, Tuple
from dataclasses import dataclass, field
import logging

logger = logging.getLogger(__name__)


@dataclass
class CommandParameter:
    """Parameter definition for a command."""
    name: str
    type: str
    required: bool = True
    description: str = ""
    default: Any = None


@dataclass 
class Command:
    """Represents a TUI command."""
    name: str
    category: str
    description: str
    handler: str
    aliases: List[str] = field(default_factory=list)
    parameters: List[CommandParameter] = field(default_factory=list)
    enabled: bool = True
    
    def matches(self, input_str: str) -> bool:
        """Check if input matches this command or its aliases."""
        if input_str == self.name:
            return True
        return input_str in self.aliases
    
    def parse_args(self, args_str: str) -> Dict[str, Any]:
        """Parse arguments string into parameter dict."""
        import shlex
        args: Dict[str, Any] = {}

        # No arguments provided
        if not args_str or not args_str.strip():
            for param in self.parameters:
                if not param.required:
                    args[param.name] = param.default
            return args

        # Use shlex to honor quotes
        try:
            parts = shlex.split(args_str)
        except ValueError:
            parts = args_str.split()

        for i, param in enumerate(self.parameters):
            if i < len(parts):
                raw = parts[i]
                if param.type == "int":
                    try:
                        args[param.name] = int(raw)
                    except ValueError:
                        args[param.name] = param.default
                elif param.type == "bool":
                    args[param.name] = str(raw).lower() in ("true", "yes", "1", "on")
                else:
                    args[param.name] = raw
            elif not param.required:
                args[param.name] = param.default
            # else: leave missing required param unfilled

        return args


class CommandRegistry:
    """
    Registry for TUI commands loaded from YAML configuration.
    
    Features:
    - Load commands from commands.yml
    - Support for aliases
    - Command categorization
    - Plugin extension support (future)
    - MCP integration (future)
    """
    
    def __init__(self, config_path: Optional[str] = None):
        self.commands: Dict[str, Command] = {}
        self.aliases: Dict[str, str] = {}
        self.categories: Dict[str, List[Command]] = {}
        self.handlers: Dict[str, Callable] = {}
        
        # Load configuration
        if config_path:
            self.config_path = Path(config_path)
        else:
            # Default to commands.yml in the same directory as this file
            self.config_path = Path(__file__).parent / "commands.yml"
        
        self.load_commands()
    
    def load_commands(self) -> None:
        """Load commands from YAML configuration."""
        if not self.config_path.exists():
            logger.warning(f"Commands config not found: {self.config_path}")
            self._register_builtin_commands()
            return
        
        try:
            with open(self.config_path, 'r') as f:
                config = yaml.safe_load(f)
            
            # Process categories
            for cat_def in config.get('categories', []):
                self.categories[cat_def['name']] = []
            
            # Process commands
            for cmd_def in config.get('commands', []):
                command = self._create_command(cmd_def)
                if command.enabled:
                    self.register(command)
            
            logger.info(f"Loaded {len(self.commands)} commands from {self.config_path}")
            
        except Exception as e:
            logger.error(f"Error loading commands config: {e}")
            self._register_builtin_commands()
    
    def _create_command(self, cmd_def: Dict[str, Any]) -> Command:
        """Create a Command from YAML definition."""
        # Parse parameters
        params = []
        for param_def in cmd_def.get('parameters', []):
            param = CommandParameter(
                name=param_def['name'],
                type=param_def.get('type', 'string'),
                required=param_def.get('required', True),
                description=param_def.get('description', ''),
                default=param_def.get('default')
            )
            params.append(param)
        
        return Command(
            name=cmd_def['name'],
            category=cmd_def.get('category', 'general'),
            description=cmd_def.get('description', ''),
            handler=cmd_def.get('handler', ''),
            aliases=cmd_def.get('aliases', []),
            parameters=params,
            enabled=cmd_def.get('enabled', True)
        )
    
    def register(self, command: Command) -> None:
        """Register a command."""
        self.commands[command.name] = command
        
        # Register aliases
        for alias in command.aliases:
            self.aliases[alias] = command.name
        
        # Add to category
        if command.category not in self.categories:
            self.categories[command.category] = []
        self.categories[command.category].append(command)
    
    def register_handler(self, handler_name: str, handler: Callable) -> None:
        """Register a command handler function."""
        self.handlers[handler_name] = handler
    
    def find_command(self, input_str: str) -> Optional[Command]:
        """Find command by exact name or alias (no partial matching)."""
        if input_str in self.commands:
            return self.commands[input_str]
        if input_str in self.aliases:
            return self.commands[self.aliases[input_str]]
        return None
    
    def parse_input(self, input_str: str) -> Tuple[Optional[Command], Dict[str, Any]]:
        """
        Parse user input into command and arguments.
        
        Returns:
            Tuple of (Command, arguments dict) or (None, {}) if not found
        """
        input_str = input_str.strip()
        if not input_str:
            return None, {}
        
        # Remove leading slash if present
        if input_str.startswith('/'):
            input_str = input_str[1:]
        
        # Tokenize input
        parts = input_str.split()
        command: Optional[Command] = None
        remaining_args = ""

        # 1) Exact match on full string first
        cmd_candidate = input_str
        if cmd_candidate in self.commands or cmd_candidate in self.aliases:
            command = self.find_command(cmd_candidate)
            if command:
                used_tokens = len(command.name.split())
                remaining_args = " ".join(parts[used_tokens:])

        # 2) Longest prefix match by command tokens
        if not command:
            best_name = None
            best_len = -1
            for cmd_name in self.commands.keys():
                cmd_tokens = cmd_name.split()
                if len(parts) >= len(cmd_tokens) and parts[:len(cmd_tokens)] == cmd_tokens:
                    if len(cmd_tokens) > best_len:
                        best_name = cmd_name
                        best_len = len(cmd_tokens)
            if best_name:
                command = self.commands[best_name]
                remaining_args = " ".join(parts[best_len:])

        if not command:
            return None, {}

        # Parse arguments from the remaining string
        try:
            args = command.parse_args(remaining_args) if remaining_args else {}
        except ValueError as e:
            logger.error(f"Error parsing command arguments: {e}")
            args = {}
        
        return command, args
    
    def get_suggestions(self, partial: str) -> List[str]:
        """Get command suggestions for autocomplete."""
        if not partial:
            return []
        
        # Remove leading slash
        if partial.startswith('/'):
            partial = partial[1:]
        
        suggestions: List[str] = []
        
        # Check direct commands
        for cmd_name in self.commands:
            if cmd_name.startswith(partial):
                suggestions.append(f"/{cmd_name}")
        
        # Check aliases
        for alias in self.aliases:
            if alias.startswith(partial):
                suggestions.append(f"/{alias}")
        
        return sorted(suggestions)[:10]  # Limit to 10 suggestions
    
    def get_help_text(self) -> str:
        """Generate help text for all commands."""
        lines = ["**Available Commands:**\n"]
        
        for category, commands in sorted(self.categories.items()):
            if not commands:
                continue
            
            # Category header
            cat_title = category.replace('_', ' ').title()
            lines.append(f"\n**{cat_title}:**")
            
            # Commands in category
            for cmd in sorted(commands, key=lambda c: c.name):
                # Command with aliases
                cmd_str = f"/{cmd.name}"
                if cmd.aliases:
                    alias_str = ", ".join(f"/{a}" for a in cmd.aliases)
                    cmd_str += f" ({alias_str})"
                
                lines.append(f"- `{cmd_str}` - {cmd.description}")
                
                # Parameters
                if cmd.parameters:
                    for param in cmd.parameters:
                        req = "required" if param.required else "optional"
                        lines.append(f"    • {param.name} ({param.type}, {req}): {param.description}")
        
        return "\n".join(lines)
    
    def _register_builtin_commands(self) -> None:
        """Register minimal builtin commands as fallback."""
        builtins = [
            Command("help", "system", "Show help", "_show_help", ["h", "?"]),
            Command("clear", "chat", "Clear chat", "action_clear_log", ["cls"]),
            Command("quit", "system", "Exit", "action_quit", ["exit", "q"]),
            Command("debug", "debug", "Show debug info", "action_show_debug"),
        ]
        
        for cmd in builtins:
            self.register(cmd)
