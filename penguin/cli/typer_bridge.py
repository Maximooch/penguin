"""
Bridge between Command Registry and Typer CLI

This module provides integration between the unified command registry
and the existing Typer app structure, enabling gradual migration
while maintaining backward compatibility.
"""

import asyncio
import traceback
from typing import Any, Dict, List, Optional
import typer
from rich.console import Console
import logging

from penguin.cli.commands import CommandRegistry, CommandCategory

logger = logging.getLogger(__name__)
console = Console()


class TyperBridge:
    """
    Bridges the unified command registry with Typer apps.

    This allows us to:
    1. Use the same command logic for both CLI and interactive modes
    2. Gradually migrate Typer commands to the registry
    3. Maintain backward compatibility during refactoring
    """

    def __init__(self, registry: Optional[CommandRegistry] = None):
        self.registry = registry or CommandRegistry.get_instance()
        self._interface = None  # Lazy-loaded PenguinInterface

    @property
    def interface(self):
        """Lazy-load PenguinInterface to avoid circular imports"""
        if self._interface is None:
            from penguin.cli.interface import PenguinInterface
            self._interface = PenguinInterface()
        return self._interface

    def create_typer_command(self, command_name: str, typer_app: typer.Typer = None):
        """
        Create a Typer command that delegates to the registry.

        Args:
            command_name: Name of the command in the registry
            typer_app: Optional Typer app to add the command to

        Returns:
            A Typer command function
        """
        cmd_def = self.registry.commands.get(command_name)
        if not cmd_def:
            raise ValueError(f"Command '{command_name}' not found in registry")

        # Create the Typer command function
        def typer_command(*args, **kwargs):
            """Auto-generated Typer command from registry"""
            # Convert Typer arguments to command args list
            args_list = list(args)

            # Add kwargs as key=value pairs
            for key, value in kwargs.items():
                if value is not None:
                    args_list.append(f"{key}={value}")

            # Run the async command
            try:
                # Get or create event loop
                try:
                    loop = asyncio.get_running_loop()
                    # We're already in an async context
                    result = asyncio.create_task(
                        self.registry.execute(command_name, args_list)
                    )
                except RuntimeError:
                    # No running loop, create one
                    result = asyncio.run(
                        self.registry.execute(command_name, args_list)
                    )

                # Handle the result
                if isinstance(result, dict):
                    if "error" in result:
                        console.print(f"[red]Error: {result['error']}[/red]")
                        if "details" in result:
                            console.print(f"[dim]{result['details']}[/dim]")
                        raise typer.Exit(code=1)
                    elif "status" in result:
                        if result["status"] == "exit":
                            raise typer.Exit(code=0)
                        console.print(result["status"])
                    elif "help" in result:
                        console.print(result["help"])
                    else:
                        # Pretty print other results
                        import json
                        console.print(json.dumps(result, indent=2, default=str))

            except KeyboardInterrupt:
                console.print("\n[yellow]Command interrupted[/yellow]")
                raise typer.Exit(code=0)
            except Exception as e:
                console.print(f"[red]Command failed: {e}[/red]")
                logger.error(f"Command {command_name} failed", exc_info=True)
                raise typer.Exit(code=1)

        # Set function metadata for Typer
        typer_command.__name__ = command_name
        typer_command.__doc__ = cmd_def.description

        # If a Typer app was provided, register the command
        if typer_app:
            typer_app.command(
                name=command_name,
                help=cmd_def.description
            )(typer_command)

        return typer_command

    def register_subcommands(self, typer_app: typer.Typer, category: CommandCategory):
        """
        Register all commands from a category as Typer subcommands.

        Args:
            typer_app: The Typer app to add commands to
            category: The command category to register
        """
        commands = self.registry.get_commands_by_category(category)

        for cmd_def in commands:
            # Skip if command already exists in Typer app
            existing_commands = getattr(typer_app, 'registered_commands', [])
            if cmd_def.name not in existing_commands:
                self.create_typer_command(cmd_def.name, typer_app)
                logger.debug(f"Registered {cmd_def.name} with Typer app")

    async def execute_legacy_handler(self, handler_name: str, *args, **kwargs):
        """
        Execute a legacy handler from PenguinInterface.

        This provides backward compatibility for commands that haven't
        been migrated to the registry yet.

        Args:
            handler_name: Name of the method in PenguinInterface
            *args: Positional arguments for the handler
            **kwargs: Keyword arguments for the handler

        Returns:
            Handler result
        """
        # Initialize interface if needed
        if not self.interface.core:
            await self.interface.initialize()

        # Get the handler method
        handler = getattr(self.interface, handler_name, None)
        if not handler:
            raise ValueError(f"Handler '{handler_name}' not found in PenguinInterface")

        # Execute handler (handle both sync and async)
        if asyncio.iscoroutinefunction(handler):
            return await handler(*args, **kwargs)
        else:
            return handler(*args, **kwargs)

    def migrate_typer_command(self,
                            typer_cmd: Any,
                            command_name: str,
                            category: CommandCategory,
                            registry_handler: Optional[Any] = None):
        """
        Migrate an existing Typer command to use the registry.

        This wraps the existing Typer command to use the registry
        while maintaining the same interface.

        Args:
            typer_cmd: The existing Typer command function
            command_name: Name for the command in the registry
            category: Category for the command
            registry_handler: Optional custom handler for the registry
        """
        # If no custom handler provided, create one that calls the Typer command
        if not registry_handler:
            async def registry_handler(core: Any, args: List[str]) -> Dict[str, Any]:
                """Wrapper for legacy Typer command"""
                try:
                    # Call the original Typer command
                    # This is a simplified example - real implementation would
                    # need to parse args properly for the Typer command
                    result = typer_cmd(*args)
                    return {"status": "success", "result": result}
                except Exception as e:
                    return {"error": str(e), "details": traceback.format_exc()}

        # Register with the registry
        self.registry.register(
            name=command_name,
            category=category,
            description=typer_cmd.__doc__ or f"Migrated {command_name} command",
            requires_core=True
        )(registry_handler)

        logger.info(f"Migrated Typer command '{command_name}' to registry")


# Create global bridge instance
bridge = TyperBridge()


def create_unified_typer_app() -> typer.Typer:
    """
    Create a Typer app that uses the unified command registry.

    This creates a new Typer app structure that delegates all
    commands to the registry, eliminating duplication.

    Returns:
        A configured Typer application
    """
    app = typer.Typer(
        name="penguin",
        help="🐧 Penguin AI Assistant - Unified CLI",
        rich_markup_mode="rich"
    )

    # Create category-based subapps
    category_apps = {
        CommandCategory.CHAT: typer.Typer(help="Chat and conversation management"),
        CommandCategory.PROJECT: typer.Typer(help="Project management"),
        CommandCategory.TASK: typer.Typer(help="Task management"),
        CommandCategory.AGENT: typer.Typer(help="Agent management"),
        CommandCategory.CONFIG: typer.Typer(help="Configuration management"),
        CommandCategory.MODEL: typer.Typer(help="Model selection"),
        CommandCategory.CONTEXT: typer.Typer(help="Context file management"),
        CommandCategory.DEBUG: typer.Typer(help="Debug and diagnostic tools"),
    }

    # Register subapps with main app
    for category, subapp in category_apps.items():
        if category != CommandCategory.SYSTEM:  # System commands go at root level
            app.add_typer(subapp, name=category.value)

            # Register commands from registry
            bridge.register_subcommands(subapp, category)

    # Register system commands at root level
    for cmd_def in bridge.registry.get_commands_by_category(CommandCategory.SYSTEM):
        bridge.create_typer_command(cmd_def.name, app)

    return app


def integrate_with_existing_app(app: typer.Typer):
    """
    Integrate the command registry with an existing Typer app.

    This allows gradual migration of commands to the registry
    while keeping the existing app structure.

    Args:
        app: The existing Typer application
    """
    # Hook into the app to intercept command execution
    original_callback = app.callback

    @app.callback()
    def unified_callback(ctx: typer.Context):
        """Unified callback that checks registry first"""
        # Check if this is a registry command
        if ctx.invoked_subcommand:
            command_name = ctx.invoked_subcommand

            # Try to find in registry
            if command_name in bridge.registry.commands:
                # Let the registry handle it
                logger.debug(f"Routing {command_name} through registry")
                # The actual execution will happen in the command function
            elif command_name in bridge.registry.aliases:
                # Resolve alias and execute
                actual_command = bridge.registry.aliases[command_name]
                logger.debug(f"Routing alias {command_name} -> {actual_command}")
                ctx.invoked_subcommand = actual_command

        # Call original callback if it exists
        if original_callback and callable(original_callback):
            return original_callback(ctx)

    logger.info("Integrated command registry with existing Typer app")