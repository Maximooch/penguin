"""
Unified Command Registry for Penguin CLI

This module provides a centralized command registry that eliminates duplication
between cli.py and interface.py. All commands are defined once and reused.

Key Features:
- Decorator-based command registration
- Automatic command discovery and validation
- Type-safe command definitions
- Direct integration with PenguinCore
"""

import asyncio
from dataclasses import dataclass
from enum import Enum
from functools import wraps
from typing import Any, Callable, Dict, List, Optional, Union, Awaitable
import logging
import traceback

logger = logging.getLogger(__name__)

# Type alias for command handlers
CommandHandler = Callable[..., Awaitable[Dict[str, Any]]]


class CommandCategory(Enum):
    """Categories for organizing commands"""
    CHAT = "chat"
    PROJECT = "project"
    TASK = "task"
    AGENT = "agent"
    CONFIG = "config"
    MODEL = "model"
    CONTEXT = "context"
    DEBUG = "debug"
    SYSTEM = "system"


@dataclass
class CommandDefinition:
    """Definition of a CLI command"""
    name: str
    category: CommandCategory
    handler: CommandHandler
    description: str
    usage: Optional[str] = None
    aliases: Optional[List[str]] = None
    requires_core: bool = True
    hidden: bool = False


class CommandRegistry:
    """
    Centralized registry for all CLI commands.

    Replaces duplicate command implementations in:
    - cli.py subcommands (lines 1195-1960)
    - interface.py handlers (lines 368-1639)
    """

    _instance: Optional['CommandRegistry'] = None

    def __init__(self):
        self.commands: Dict[str, CommandDefinition] = {}
        self.aliases: Dict[str, str] = {}
        self.core: Optional[Any] = None  # PenguinCore instance
        logger.debug("CommandRegistry initialized")

    @classmethod
    def get_instance(cls) -> 'CommandRegistry':
        """Get or create singleton instance"""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def set_core(self, core: Any) -> None:
        """Set the PenguinCore instance for command execution"""
        self.core = core
        logger.debug("CommandRegistry connected to PenguinCore")

    def register(self,
                 name: str,
                 category: CommandCategory,
                 description: str,
                 usage: Optional[str] = None,
                 aliases: Optional[List[str]] = None,
                 requires_core: bool = True,
                 hidden: bool = False) -> Callable:
        """
        Decorator for registering commands.

        Example:
            @registry.register("chat", CommandCategory.CHAT, "Manage conversations")
            async def chat_command(args: List[str]) -> Dict[str, Any]:
                ...
        """
        def decorator(func: CommandHandler) -> CommandHandler:
            # Create command definition
            cmd_def = CommandDefinition(
                name=name,
                category=category,
                handler=func,
                description=description,
                usage=usage,
                aliases=aliases,
                requires_core=requires_core,
                hidden=hidden
            )

            # Register command
            self.commands[name] = cmd_def

            # Register aliases
            if aliases:
                for alias in aliases:
                    self.aliases[alias] = name

            logger.debug(f"Registered command: {name} ({category.value})")

            @wraps(func)
            async def wrapper(*args, **kwargs) -> Dict[str, Any]:
                # Check core requirement
                if requires_core and not self.core:
                    return {"error": "Core not initialized for command execution"}

                try:
                    # Execute command
                    result = await func(*args, **kwargs)
                    return result
                except Exception as e:
                    logger.error(f"Error in command {name}: {e}", exc_info=True)
                    return {
                        "error": str(e),
                        "details": traceback.format_exc()
                    }

            return wrapper

        return decorator

    async def execute(self, command: str, args: List[str]) -> Dict[str, Any]:
        """
        Execute a registered command.

        Args:
            command: Command name or alias
            args: Command arguments

        Returns:
            Command execution result
        """
        # Resolve aliases
        if command in self.aliases:
            command = self.aliases[command]

        # Find command
        if command not in self.commands:
            return {
                "error": f"Unknown command: {command}",
                "suggestions": self.get_suggestions(command)
            }

        cmd_def = self.commands[command]

        # Execute handler
        return await cmd_def.handler(self.core, args)

    def get_suggestions(self, partial: str) -> List[str]:
        """Get command suggestions for partial input"""
        suggestions = []

        # Check exact matches first
        for name in self.commands.keys():
            if name.startswith(partial):
                suggestions.append(name)

        # Check aliases
        for alias, target in self.aliases.items():
            if alias.startswith(partial) and target not in suggestions:
                suggestions.append(f"{alias} -> {target}")

        return sorted(suggestions)[:5]

    def get_commands_by_category(self, category: CommandCategory) -> List[CommandDefinition]:
        """Get all commands in a specific category"""
        return [
            cmd for cmd in self.commands.values()
            if cmd.category == category and not cmd.hidden
        ]

    def get_help_text(self, command: Optional[str] = None) -> str:
        """Generate help text for a command or all commands"""
        if command:
            # Specific command help
            if command in self.aliases:
                command = self.aliases[command]

            if command not in self.commands:
                return f"Unknown command: {command}"

            cmd_def = self.commands[command]
            help_text = f"**{cmd_def.name}** - {cmd_def.description}\n"

            if cmd_def.usage:
                help_text += f"Usage: {cmd_def.usage}\n"

            if cmd_def.aliases:
                help_text += f"Aliases: {', '.join(cmd_def.aliases)}\n"

            return help_text

        # All commands help
        help_text = "**Available Commands**\n\n"

        for category in CommandCategory:
            commands = self.get_commands_by_category(category)
            if commands:
                help_text += f"**{category.value.title()}**\n"
                for cmd in commands:
                    help_text += f"  /{cmd.name}"
                    if cmd.aliases:
                        help_text += f" ({', '.join(cmd.aliases)})"
                    help_text += f" - {cmd.description}\n"
                help_text += "\n"

        return help_text


# Create singleton registry instance
registry = CommandRegistry.get_instance()


# =============================================================================
# CHAT COMMANDS
# =============================================================================

@registry.register(
    "chat",
    CommandCategory.CHAT,
    "Manage conversations",
    usage="/chat [list|load|summary]",
    aliases=["conv", "conversation"]
)
async def chat_command(core: Any, args: List[str]) -> Dict[str, Any]:
    """Handle conversation management"""
    if not args:
        return {"error": "Missing subcommand. Use: list, load, or summary"}

    subcmd = args[0].lower()

    if subcmd == "list":
        conversations = core.list_conversations(limit=20)
        return {"conversations": conversations}

    elif subcmd == "load" and len(args) > 1:
        session_id = args[1]
        success = core.conversation_manager.load(session_id)
        if success:
            return {"status": f"Loaded conversation {session_id}"}
        return {"error": f"Failed to load conversation {session_id}"}

    elif subcmd == "summary":
        history = core.conversation_manager.conversation.get_history()
        return {"summary": history}

    return {"error": f"Unknown chat subcommand: {subcmd}"}


# =============================================================================
# PROJECT COMMANDS
# =============================================================================

@registry.register(
    "project",
    CommandCategory.PROJECT,
    "Project management",
    usage="/project [create|list|delete] [args...]"
)
async def project_command(core: Any, args: List[str]) -> Dict[str, Any]:
    """Handle project management"""
    if not args:
        return {"error": "Missing subcommand. Use: create, list, or delete"}

    action = args[0].lower()

    if action == "create" and len(args) >= 2:
        # Parse name and description
        remainder = " ".join(args[1:])
        import shlex
        try:
            parts = shlex.split(remainder)
        except ValueError:
            parts = remainder.split(" ")

        name = parts[0] if parts else ""
        description = " ".join(parts[1:]) if len(parts) > 1 else ""

        if not name:
            return {"error": "Project name required"}

        project = await core.project_manager.create_project_async(
            name=name,
            description=description
        )
        return {
            "status": f"Created project: {project.name}",
            "project_id": project.id,
            "project_name": project.name
        }

    elif action == "list":
        projects = await core.project_manager.list_projects_async()
        return {"projects": projects}

    elif action == "delete" and len(args) > 1:
        project_id = args[1]
        success = core.project_manager.storage.delete_project(project_id)
        if success:
            return {"status": f"Deleted project {project_id}"}
        return {"error": f"Failed to delete project {project_id}"}

    return {"error": f"Unknown project command: {action}"}


# =============================================================================
# TASK COMMANDS
# =============================================================================

@registry.register(
    "task",
    CommandCategory.TASK,
    "Task management",
    usage="/task [create|run|status] [args...]"
)
async def task_command(core: Any, args: List[str]) -> Dict[str, Any]:
    """Handle task management"""
    if not args:
        return {"error": "Missing subcommand. Use: create, run, or status"}

    action = args[0].lower()

    if action == "create" and len(args) >= 2:
        # Parse name and description
        remainder = " ".join(args[1:])
        import shlex
        try:
            parts = shlex.split(remainder)
        except ValueError:
            parts = remainder.split(" ")

        name = parts[0] if parts else ""
        description = " ".join(parts[1:]) if len(parts) > 1 else ""

        if not name:
            return {"error": "Task name required"}

        task = await core.project_manager.create_task_async(
            title=name,
            description=description,
            priority=1
        )
        return {
            "status": f"Created task: {task.title}",
            "task_id": task.id,
            "task_title": task.title
        }

    elif action == "run" and len(args) > 1:
        task_name = args[1]
        description = " ".join(args[2:]) if len(args) > 2 else None
        await core.start_run_mode(name=task_name, description=description)
        return {"status": f"Started task: {task_name}"}

    elif action == "status" and len(args) > 1:
        task_id = args[1]
        task = await core.project_manager.get_task_async(task_id)
        if task:
            return {
                "status": f"Task '{task.title}' status: {task.status.value}",
                "task": {
                    "id": task.id,
                    "title": task.title,
                    "status": task.status.value,
                    "description": task.description
                }
            }
        return {"error": f"Task not found: {task_id}"}

    return {"error": f"Unknown task command: {action}"}


# =============================================================================
# AGENT COMMANDS
# =============================================================================

@registry.register(
    "agent",
    CommandCategory.AGENT,
    "Agent management",
    usage="/agent [list|spawn|activate|pause|resume] [args...]"
)
async def agent_command(core: Any, args: List[str]) -> Dict[str, Any]:
    """Handle agent management"""
    if not args:
        return {"error": "Missing subcommand"}

    action = args[0].lower()

    if action == "list":
        roster = core.get_agent_roster()
        return {
            "status": f"{len(roster)} agent(s) registered",
            "agents": roster
        }

    elif action == "spawn" and len(args) > 1:
        agent_id = args[1]
        # Parse options
        persona = None
        parent = None
        activate = False

        for i in range(2, len(args)):
            arg = args[i]
            if arg.startswith("persona="):
                persona = arg.split("=", 1)[1]
            elif arg.startswith("parent="):
                parent = arg.split("=", 1)[1]
            elif arg == "activate":
                activate = True

        if parent:
            core.create_sub_agent(
                agent_id,
                parent_agent_id=parent,
            )
        else:
            core.ensure_agent_conversation(agent_id)

        # Store persona in conversation metadata if specified
        if persona:
            conv = core.conversation_manager.get_agent_conversation(agent_id)
            if conv and hasattr(conv, 'session') and conv.session:
                conv.session.metadata["persona"] = persona

        if activate:
            core.set_active_agent(agent_id)

        return {"status": f"Spawned agent {agent_id}"}

    elif action == "activate" and len(args) > 1:
        agent_id = args[1]
        core.set_active_agent(agent_id)
        return {"status": f"Activated agent {agent_id}"}

    elif action in ["pause", "resume"] and len(args) > 1:
        agent_id = args[1]
        paused = (action == "pause")
        core.set_agent_paused(agent_id, paused)
        return {"status": f"{action.title()}d agent {agent_id}"}

    return {"error": f"Unknown agent command: {action}"}


# =============================================================================
# MODEL COMMANDS
# =============================================================================

@registry.register(
    "model",
    CommandCategory.MODEL,
    "Model management",
    usage="/model [set|list] [model_id]",
    aliases=["models"]
)
async def model_command(core: Any, args: List[str]) -> Dict[str, Any]:
    """Handle model selection and listing"""
    if not args or args[0] == "list":
        models = core.list_available_models()
        return {"models": models}

    if args[0] == "set" and len(args) > 1:
        model_id = args[1]
        success = await core.load_model(model_id)
        if success:
            current = core.get_current_model()
            return {
                "status": f"Loaded model: {model_id}",
                "model": current
            }
        return {"error": f"Failed to load model: {model_id}"}

    return {"error": "Usage: /model [set|list] [model_id]"}


# =============================================================================
# CONFIG COMMANDS
# =============================================================================

@registry.register(
    "config",
    CommandCategory.CONFIG,
    "Configuration management",
    usage="/config [get|set] [key] [value]"
)
async def config_command(core: Any, args: List[str]) -> Dict[str, Any]:
    """Handle configuration management"""
    if not args:
        return {"error": "Missing subcommand. Use: get or set"}

    action = args[0].lower()

    if action == "get" and len(args) > 1:
        from penguin.config import get_config_value
        key = args[1]
        value = get_config_value(key)
        return {"key": key, "value": value}

    elif action == "set" and len(args) > 2:
        from penguin.config import set_config_value
        key = args[1]
        value = args[2]

        # Try to parse as JSON
        import json
        try:
            value = json.loads(value)
        except:
            pass  # Use as string

        path = set_config_value(key, value)
        return {
            "status": "Configuration updated",
            "key": key,
            "value": value,
            "written_to": str(path)
        }

    return {"error": f"Unknown config command: {action}"}


# =============================================================================
# AGENT EXTENDED COMMANDS
# =============================================================================

@registry.register(
    "personas",
    CommandCategory.AGENT,
    "List available agent personas",
    usage="/personas"
)
async def personas_command(core: Any, args: List[str]) -> Dict[str, Any]:
    """List all available agent personas"""
    personas = core.get_persona_catalog()
    return {"personas": personas}


@registry.register(
    "set-persona",
    CommandCategory.AGENT,
    "Set persona for an agent",
    usage="/set-persona [agent_id] [persona_name]"
)
async def set_persona_command(core: Any, args: List[str]) -> Dict[str, Any]:
    """Set the persona for a specific agent"""
    if len(args) < 2:
        return {"error": "Usage: /set-persona [agent_id] [persona_name]"}

    agent_id = args[0]
    persona_name = args[1]

    success = core.set_agent_persona(agent_id, persona_name)
    if success:
        return {"status": f"Set persona '{persona_name}' for agent {agent_id}"}
    return {"error": f"Failed to set persona for agent {agent_id}"}


@registry.register(
    "agent-info",
    CommandCategory.AGENT,
    "Show detailed agent information",
    usage="/agent-info [agent_id]"
)
async def agent_info_command(core: Any, args: List[str]) -> Dict[str, Any]:
    """Show detailed information about a specific agent"""
    if not args:
        return {"error": "Agent ID required"}

    agent_id = args[0]
    agent_info = core.get_agent_info(agent_id)

    if agent_info:
        return {"agent_info": agent_info}
    return {"error": f"Agent not found: {agent_id}"}


# =============================================================================
# MESSAGE COMMANDS
# =============================================================================

@registry.register(
    "msg-to-agent",
    CommandCategory.CHAT,
    "Send message to specific agent",
    usage="/msg-to-agent [agent_id] [message]",
    aliases=["msg-agent", "tell"]
)
async def msg_to_agent_command(core: Any, args: List[str]) -> Dict[str, Any]:
    """Send a message to a specific agent"""
    if len(args) < 2:
        return {"error": "Usage: /msg-to-agent [agent_id] [message]"}

    agent_id = args[0]
    message = " ".join(args[1:])

    # Route message to specific agent
    success = await core.send_to_agent(agent_id, message)
    if success:
        return {"status": f"Message sent to agent {agent_id}"}
    return {"error": f"Failed to send message to agent {agent_id}"}


@registry.register(
    "msg-to-human",
    CommandCategory.CHAT,
    "Send message for human response",
    usage="/msg-to-human [message]",
    aliases=["ask-human", "human"]
)
async def msg_to_human_command(core: Any, args: List[str]) -> Dict[str, Any]:
    """Send a message requiring human response"""
    if not args:
        return {"error": "Message required"}

    message = " ".join(args)

    # Mark message as requiring human response
    await core.emit_human_prompt(message)
    return {"status": "Waiting for human response", "prompt": message}


# =============================================================================
# COORDINATOR COMMANDS (Multi-Agent)
# =============================================================================

@registry.register(
    "coord-spawn",
    CommandCategory.AGENT,
    "Spawn coordinator for multi-agent workflows",
    usage="/coord-spawn [workflow_type]"
)
async def coord_spawn_command(core: Any, args: List[str]) -> Dict[str, Any]:
    """Spawn a multi-agent coordinator"""
    workflow_type = args[0] if args else "default"

    try:
        coordinator = await core.spawn_coordinator(workflow_type)
        return {
            "status": f"Spawned coordinator for {workflow_type} workflow",
            "coordinator_id": coordinator.id if hasattr(coordinator, 'id') else "coordinator"
        }
    except Exception as e:
        return {"error": f"Failed to spawn coordinator: {e}"}


@registry.register(
    "coord-broadcast",
    CommandCategory.AGENT,
    "Broadcast message to all agents",
    usage="/coord-broadcast [message]"
)
async def coord_broadcast_command(core: Any, args: List[str]) -> Dict[str, Any]:
    """Broadcast a message to all active agents"""
    if not args:
        return {"error": "Message required"}

    message = " ".join(args)

    # Get all active agents and send message
    roster = core.get_agent_roster()
    sent_to = []

    for agent_id in roster:
        if await core.send_to_agent(agent_id, message):
            sent_to.append(agent_id)

    return {
        "status": f"Broadcasted to {len(sent_to)} agents",
        "agents": sent_to
    }


@registry.register(
    "coord-role-chain",
    CommandCategory.AGENT,
    "Execute role-based agent chain",
    usage="/coord-role-chain [role1,role2,...] [message]"
)
async def coord_role_chain_command(core: Any, args: List[str]) -> Dict[str, Any]:
    """Execute a chain of agents by role"""
    if len(args) < 2:
        return {"error": "Usage: /coord-role-chain [role1,role2,...] [message]"}

    roles = args[0].split(',')
    message = " ".join(args[1:])

    try:
        result = await core.execute_role_chain(roles, message)
        return {
            "status": "Role chain executed",
            "roles": roles,
            "result": result
        }
    except Exception as e:
        return {"error": f"Role chain failed: {e}"}


# =============================================================================
# SYSTEM COMMANDS
# =============================================================================

@registry.register(
    "help",
    CommandCategory.SYSTEM,
    "Show help information",
    usage="/help [command]",
    aliases=["h", "?"],
    requires_core=False
)
async def help_command(core: Any, args: List[str]) -> Dict[str, Any]:
    """Show help for commands"""
    registry = CommandRegistry.get_instance()

    if args:
        help_text = registry.get_help_text(args[0])
    else:
        help_text = registry.get_help_text()

    return {"help": help_text}


@registry.register(
    "exit",
    CommandCategory.SYSTEM,
    "Exit the application",
    aliases=["quit", "q"],
    requires_core=False
)
async def exit_command(core: Any, args: List[str]) -> Dict[str, Any]:
    """Exit the application"""
    return {"status": "exit", "message": "Goodbye!"}


@registry.register(
    "tokens",
    CommandCategory.DEBUG,
    "Show token usage",
    usage="/tokens [reset|detail]"
)
async def tokens_command(core: Any, args: List[str]) -> Dict[str, Any]:
    """Show or reset token usage"""
    if args and args[0] == "reset":
        # Reset would go here if supported
        return {"status": "Token reset not yet implemented"}

    elif args and args[0] == "detail":
        usage = core.conversation_manager.get_token_usage()
        return {"token_usage_detailed": usage}

    else:
        usage = core.conversation_manager.get_token_usage()
        return {"token_usage": usage}


@registry.register(
    "context",
    CommandCategory.CONTEXT,
    "Manage context files",
    usage="/context [list|load FILE]"
)
async def context_command(core: Any, args: List[str]) -> Dict[str, Any]:
    """Manage context files"""
    if not args or args[0] == "list":
        files = core.list_context_files()
        return {"context_files": files}

    if args[0] == "load" and len(args) > 1:
        file_path = args[1]
        success = core.conversation_manager.load_context_file(file_path)
        if success:
            return {"status": f"Loaded context file: {file_path}"}
        return {"error": f"Failed to load context file: {file_path}"}

    return {"error": "Unknown context command"}


# =============================================================================
# CHECKPOINT COMMANDS (Phase 2 - Kimi CLI Patterns)
# =============================================================================

@registry.register(
    "checkpoint",
    CommandCategory.CONTEXT,
    "Create a manual checkpoint of current conversation",
    usage="/checkpoint [name] [description]",
    aliases=["cp", "save"]
)
async def checkpoint_command(core: Any, args: List[str]) -> Dict[str, Any]:
    """Create a manual checkpoint of the current conversation state"""
    name = args[0] if args else None
    description = " ".join(args[1:]) if len(args) > 1 else None
    
    try:
        checkpoint_id = await core.create_checkpoint(name=name, description=description)
        
        if checkpoint_id:
            result = {
                "status": f"✓ Checkpoint created: {checkpoint_id}",
                "checkpoint_id": checkpoint_id
            }
            if name:
                result["checkpoint_name"] = name
            if description:
                result["checkpoint_description"] = description
            return result
        else:
            return {"error": "Failed to create checkpoint"}
            
    except Exception as e:
        logger.error(f"Error creating checkpoint: {e}", exc_info=True)
        return {"error": f"Failed to create checkpoint: {str(e)}"}


@registry.register(
    "rollback",
    CommandCategory.CONTEXT,
    "Rollback conversation to a specific checkpoint",
    usage="/rollback <checkpoint_id>",
    aliases=["revert", "undo"]
)
async def rollback_command(core: Any, args: List[str]) -> Dict[str, Any]:
    """Rollback to a specific checkpoint"""
    if not args:
        return {"error": "Checkpoint ID required. Usage: /rollback <checkpoint_id>"}
    
    checkpoint_id = args[0]
    
    try:
        success = await core.rollback_to_checkpoint(checkpoint_id)
        
        if success:
            return {
                "status": f"✓ Rolled back to checkpoint: {checkpoint_id}",
                "checkpoint_id": checkpoint_id
            }
        else:
            return {"error": f"Failed to rollback to checkpoint {checkpoint_id}"}
            
    except Exception as e:
        logger.error(f"Error rolling back to checkpoint: {e}", exc_info=True)
        return {"error": f"Rollback failed: {str(e)}"}


@registry.register(
    "checkpoints",
    CommandCategory.CONTEXT,
    "List available checkpoints",
    usage="/checkpoints [limit]",
    aliases=["list-checkpoints", "cps"]
)
async def checkpoints_command(core: Any, args: List[str]) -> Dict[str, Any]:
    """List available checkpoints for the current session"""
    limit = 20  # Default limit
    
    if args:
        try:
            limit = int(args[0])
        except ValueError:
            return {"error": f"Invalid limit: {args[0]}. Must be a number."}
    
    try:
        checkpoints = core.list_checkpoints(limit=limit)
        
        if not checkpoints:
            return {"status": "No checkpoints found", "checkpoints": []}
        
        return {
            "status": f"Found {len(checkpoints)} checkpoint(s)",
            "checkpoints": checkpoints,
            "count": len(checkpoints)
        }
        
    except Exception as e:
        logger.error(f"Error listing checkpoints: {e}", exc_info=True)
        return {"error": f"Failed to list checkpoints: {str(e)}"}


@registry.register(
    "branch",
    CommandCategory.CONTEXT,
    "Create a new conversation branch from a checkpoint",
    usage="/branch <checkpoint_id> [name] [description]",
    aliases=["fork"]
)
async def branch_command(core: Any, args: List[str]) -> Dict[str, Any]:
    """Create a new branch from a checkpoint"""
    if not args:
        return {"error": "Checkpoint ID required. Usage: /branch <checkpoint_id> [name] [description]"}
    
    checkpoint_id = args[0]
    name = args[1] if len(args) > 1 else None
    description = " ".join(args[2:]) if len(args) > 2 else None
    
    try:
        branch_id = await core.branch_from_checkpoint(
            checkpoint_id=checkpoint_id,
            name=name,
            description=description
        )
        
        if branch_id:
            result = {
                "status": f"✓ Branch created: {branch_id}",
                "branch_id": branch_id,
                "source_checkpoint": checkpoint_id
            }
            if name:
                result["branch_name"] = name
            return result
        else:
            return {"error": f"Failed to create branch from checkpoint {checkpoint_id}"}
            
    except Exception as e:
        logger.error(f"Error creating branch: {e}", exc_info=True)
        return {"error": f"Branch creation failed: {str(e)}"}


# =============================================================================
# ENHANCED CONTEXT WINDOW COMMANDS (Phase 3 - Kimi CLI Patterns)
# =============================================================================

@registry.register(
    "truncations",
    CommandCategory.DEBUG,
    "Show recent context window truncation events",
    usage="/truncations [limit]",
    aliases=["trunc"]
)
async def truncations_command(core: Any, args: List[str]) -> Dict[str, Any]:
    """Display recent truncation events from context window management"""
    limit = 10  # Default limit
    
    if args:
        try:
            limit = int(args[0])
        except ValueError:
            return {"error": f"Invalid limit: {args[0]}. Must be a number."}
    
    try:
        # Get token usage which includes truncation data
        usage = core.conversation_manager.get_token_usage()
        truncations = usage.get("truncations", {})
        recent_events = truncations.get("recent_events", [])
        
        if not recent_events:
            return {
                "status": "No truncation events yet",
                "truncations": [],
                "summary": "Context window is within budget"
            }
        
        # Limit the results
        limited_events = recent_events[:limit]
        
        return {
            "status": f"Found {len(recent_events)} truncation event(s)",
            "truncations": limited_events,
            "count": len(recent_events),
            "total_messages_removed": truncations.get("messages_removed", 0),
            "total_tokens_freed": truncations.get("tokens_freed", 0),
            "total_events": truncations.get("total_truncations", 0)
        }
        
    except Exception as e:
        logger.error(f"Error getting truncation events: {e}", exc_info=True)
        return {"error": f"Failed to get truncations: {str(e)}"}