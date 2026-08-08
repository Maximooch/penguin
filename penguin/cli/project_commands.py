"""Project and task command registration and execution."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any, Optional

import typer

from penguin.cli.command_services import (
    AmbiguousProjectError,
    InvalidTaskStateError,
    NoProjectTasksError,
    NoReadyProjectTasksError,
    ProjectMutationError,
    ProjectNotFoundError,
    TaskMutationError,
    TaskNotFoundError,
    complete_task as complete_task_service,
    create_task as create_task_service,
    delete_project_and_tasks,
    delete_task as delete_task_service,
    list_project_summaries,
    list_tasks as list_tasks_service,
    prepare_project_start,
    resolve_project_identifier,
    start_task as start_task_service,
)
from penguin.config import GITHUB_REPOSITORY
from penguin.project.git_manager import GitManager
from penguin.project.spec_parser import parse_project_specification_from_markdown
from penguin.project.task_executor import ProjectTaskExecutor
from penguin.project.validation_manager import ValidationManager
from penguin.project.workflow_orchestrator import WorkflowOrchestrator
from penguin.run_mode import RunMode

__all__ = ["bind_project_commands"]


def bind_project_commands(
    project_app: typer.Typer,
    initialize: Callable[..., Awaitable[None]],
    core_getter: Callable[[], Any],
    workspace_getter: Callable[[], Path],
    console_getter: Callable[[], Any],
) -> dict[str, Any]:
    """Register project/task commands and return compatibility exports."""

    _core: Any = None

    async def _initialize_core_components_globally(**kwargs: Any) -> None:
        nonlocal _core
        await initialize(**kwargs)
        _core = core_getter()

    def _workspace_path() -> Path:
        return workspace_getter()

    def _console() -> Any:
        return console_getter()

    @project_app.command("init")
    def project_init(
        name: str = typer.Argument(..., help="Project name"),
        blueprint_path: Optional[Path] = typer.Option(
            None,
            "--blueprint",
            help="Path to a Blueprint file to parse and sync during initialization.",
            exists=True,
            file_okay=True,
            dir_okay=False,
            readable=True,
        ),
        description: Optional[str] = typer.Option(
            None, "--description", "-d", help="Project description"
        ),
        workspace_path: Optional[str] = typer.Option(
            None, "--workspace", "-w", help="Project workspace path"
        ),
    ):
        """Initialize a project and optionally sync a Blueprint into it."""

        async def _async_project_init():
            _console().print(f"[bold cyan]🐧 Initializing project:[/bold cyan] {name}")

            await _initialize_core_components_globally()

            if not _core or not _core.project_manager:
                _console().print("[red]Error: Project manager not available[/red]")
                raise typer.Exit(code=1)

            resolved_workspace = None
            if workspace_path:
                resolved_workspace = Path(workspace_path).expanduser().resolve()

            project = None
            try:
                project = await _core.project_manager.create_project_async(
                    name=name,
                    description=description or f"Project: {name}",
                    workspace_path=resolved_workspace,
                )

                _console().print("[green]✓ Project initialized successfully![/green]")
                _console().print(f"  ID: {project.id}")
                _console().print(f"  Name: {project.name}")
                _console().print(f"  Description: {project.description}")
                if resolved_workspace:
                    _console().print(f"  Workspace (explicit): {resolved_workspace}")
                elif project.workspace_path:
                    _console().print(f"  Workspace (default): {project.workspace_path}")

                if blueprint_path is None:
                    return

                from penguin.project.blueprint_parser import (
                    BlueprintParseError,
                    BlueprintParser,
                )

                parser = BlueprintParser(base_path=blueprint_path.parent)
                blueprint = parser.parse_file(blueprint_path)
                diagnostics = parser.lint_blueprint(
                    blueprint, source=str(blueprint_path)
                )
                if diagnostics.has_errors:
                    if project is not None:
                        await _delete_project_and_tasks_async(project.id)
                    _console().print(
                        "[red]Blueprint validation failed. Project initialization rolled back.[/red]"
                    )
                    for diagnostic in diagnostics.diagnostics:
                        prefix = diagnostic.severity.upper()
                        location = (
                            f" ({diagnostic.source}:{diagnostic.line})"
                            if diagnostic.source and diagnostic.line
                            else ""
                        )
                        _console().print(
                            f"  - [{prefix}] {diagnostic.message}{location}"
                        )
                    raise typer.Exit(code=1)

                sync_result = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: _core.project_manager.sync_blueprint(
                        blueprint,
                        project_id=project.id,
                        create_missing=True,
                        update_existing=True,
                    ),
                )
                ready_tasks = await _core.project_manager.get_ready_tasks_async(
                    project.id
                )

                _console().print(f"  Blueprint: {blueprint_path}")
                _console().print(
                    f"  Tasks created: {len(sync_result.get('created', []))}"
                )
                _console().print(
                    f"  Tasks updated: {len(sync_result.get('updated', []))}"
                )
                _console().print(
                    f"  Tasks skipped: {len(sync_result.get('skipped', []))}"
                )
                _console().print(f"  Ready tasks: {len(ready_tasks)}")
                if diagnostics.has_warnings:
                    _console().print("[yellow]Blueprint warnings:[/yellow]")
                    for diagnostic in diagnostics.diagnostics:
                        if diagnostic.severity == "warning":
                            _console().print(f"  - {diagnostic.message}")

            except BlueprintParseError as exc:
                if project is not None:
                    await _delete_project_and_tasks_async(project.id)
                _console().print(f"[red]Blueprint parse failed: {exc}[/red]")
                raise typer.Exit(code=1)
            except typer.Exit:
                raise
            except Exception as e:
                if project is not None and blueprint_path is not None:
                    await _delete_project_and_tasks_async(project.id)
                _console().print(f"[red]Error initializing project: {e}[/red]")
                raise typer.Exit(code=1)

        asyncio.run(_async_project_init())

    @project_app.command("create")
    def project_create(
        name: str = typer.Argument(..., help="Project name"),
        description: Optional[str] = typer.Option(
            None, "--description", "-d", help="Project description"
        ),
        workspace_path: Optional[str] = typer.Option(
            None, "--workspace", "-w", help="Project workspace path"
        ),
    ):
        """Create a new project. `--workspace` uses the exact provided path."""

        async def _async_project_create():
            _console().print(f"[bold cyan]🐧 Creating project:[/bold cyan] {name}")

            # Initialize core components to access project manager
            await _initialize_core_components_globally()

            if not _core or not _core.project_manager:
                _console().print("[red]Error: Project manager not available[/red]")
                raise typer.Exit(code=1)

            try:
                resolved_workspace = None
                if workspace_path:
                    resolved_workspace = Path(workspace_path).expanduser().resolve()

                project = await _core.project_manager.create_project_async(
                    name=name,
                    description=description or f"Project: {name}",
                    workspace_path=resolved_workspace,
                )

                _console().print("[green]✓ Project created successfully![/green]")
                _console().print(f"  ID: {project.id}")
                _console().print(f"  Name: {project.name}")
                _console().print(f"  Description: {project.description}")
                if resolved_workspace:
                    _console().print(f"  Workspace (explicit): {resolved_workspace}")
                elif project.workspace_path:
                    _console().print(f"  Workspace (default): {project.workspace_path}")
                current_root = os.environ.get("PENGUIN_CWD")
                if current_root:
                    _console().print(f"  Execution root: {current_root}")

            except Exception as e:
                _console().print(f"[red]Error creating project: {e}[/red]")
                raise typer.Exit(code=1)

        asyncio.run(_async_project_create())

    @project_app.command("list")
    def project_list():
        """List all projects"""

        async def _async_project_list():
            _console().print("[bold cyan]🐧 Projects:[/bold cyan]")

            await _initialize_core_components_globally()

            if not _core or not _core.project_manager:
                _console().print("[red]Error: Project manager not available[/red]")
                raise typer.Exit(code=1)

            try:
                project_summaries = await list_project_summaries(_core.project_manager)

                if not project_summaries:
                    _console().print(
                        "[yellow]No projects found. Create one with 'penguin project create <name>'[/yellow]"
                    )
                    return

                from rich.table import Table

                table = Table(show_header=True, header_style="bold magenta")
                table.add_column("ID", style="dim", width=8)
                table.add_column("Name", style="cyan")
                table.add_column("Status", style="green")
                table.add_column("Tasks", style="yellow")
                table.add_column("Created", style="dim")

                for summary in project_summaries:
                    project = summary.project
                    table.add_row(
                        project.id[:8],
                        project.name,
                        project.status,  # Project status is a string, not an enum
                        str(summary.task_count),
                        project.created_at[:16]
                        if project.created_at
                        else "Unknown",  # created_at is ISO string, take first 16 chars (YYYY-MM-DD HH:MM)
                    )

                _console().print(table)

            except Exception as e:
                _console().print(f"[red]Error listing projects: {e}[/red]")
                raise typer.Exit(code=1)

        asyncio.run(_async_project_list())

    def _resolve_project_identifier_or_exit(project_identifier: str):
        """Resolve a project by exact ID or unique exact name, failing honestly otherwise."""
        assert _core is not None and _core.project_manager is not None

        try:
            return resolve_project_identifier(_core.project_manager, project_identifier)
        except AmbiguousProjectError:
            _console().print(
                f"[red]Ambiguous project name '{project_identifier}'. Use the project ID instead.[/red]"
            )
            raise typer.Exit(code=1)
        except ProjectNotFoundError:
            _console().print(
                f"[red]Project '{project_identifier}' was not found by exact ID or exact name.[/red]"
            )
            raise typer.Exit(code=1)

    async def _delete_project_and_tasks_async(project_id: str) -> None:
        """Delete a project and all of its tasks for honest rollback/cleanup paths."""
        assert _core is not None and _core.project_manager is not None

        await delete_project_and_tasks(_core.project_manager, project_id)

    @project_app.command("delete")
    def project_delete(
        project_id: str = typer.Argument(..., help="Project ID to delete"),
        force: bool = typer.Option(
            False, "--force", "-f", help="Force delete without confirmation"
        ),
    ):
        """Delete a project"""

        async def _async_project_delete():
            await _initialize_core_components_globally()

            if not _core or not _core.project_manager:
                _console().print("[red]Error: Project manager not available[/red]")
                raise typer.Exit(code=1)

            try:
                # Get project details first
                project = await _core.project_manager.get_project_async(project_id)
                if not project:
                    _console().print(
                        f"[red]Error: Project with ID '{project_id}' not found[/red]"
                    )
                    raise typer.Exit(code=1)

                if not force:
                    confirm = typer.confirm(
                        f"Are you sure you want to delete project '{project.name}' ({project_id[:8]})?"
                    )
                    if not confirm:
                        _console().print("[yellow]Operation cancelled[/yellow]")
                        return

                try:
                    await delete_project_and_tasks(_core.project_manager, project_id)
                except ProjectMutationError:
                    _console().print("[red]Failed to delete project[/red]")
                    raise typer.Exit(code=1)
                _console().print(
                    f"[green]✓ Project '{project.name}' deleted successfully[/green]"
                )

            except Exception as e:
                _console().print(f"[red]Error deleting project: {e}[/red]")
                raise typer.Exit(code=1)

        asyncio.run(_async_project_delete())

    @project_app.command("start")
    def project_start(
        project_identifier: str = typer.Argument(
            ..., help="Project ID or exact project name"
        ),
        continuous: bool = typer.Option(
            True,
            "--continuous/--no-continuous",
            help="Run against the ready frontier continuously or execute one task selection.",
        ),
        time_limit: Optional[int] = typer.Option(
            None,
            "--time-limit",
            help="Explicit run limit in minutes for this project start invocation.",
        ),
    ):
        """Start project execution using the existing RunMode truth path."""

        async def _async_project_start():
            await _initialize_core_components_globally()

            if not _core or not _core.project_manager:
                _console().print("[red]Error: Project manager not available[/red]")
                raise typer.Exit(code=1)

            try:
                plan = await prepare_project_start(
                    _core.project_manager, project_identifier
                )
            except AmbiguousProjectError:
                _console().print(
                    f"[red]Ambiguous project name '{project_identifier}'. Use the project ID instead.[/red]"
                )
                raise typer.Exit(code=1)
            except ProjectNotFoundError:
                _console().print(
                    f"[red]Project '{project_identifier}' was not found by exact ID or exact name.[/red]"
                )
                raise typer.Exit(code=1)
            except NoProjectTasksError as exc:
                _console().print(
                    f"[red]Project '{exc.args[0]}' has no tasks. Initialize or import a Blueprint first.[/red]"
                )
                raise typer.Exit(code=1)
            except NoReadyProjectTasksError as exc:
                _console().print(
                    f"[red]Project '{exc.args[0]}' has no ready tasks to execute.[/red]"
                )
                raise typer.Exit(code=1)

            project = plan.project
            ready_tasks = plan.ready_tasks
            _console().print(
                f"[bold blue]Starting project:[/bold blue] {project.name} ({project.id})"
            )
            _console().print(
                f"  Mode: {'continuous' if continuous else 'single-selection'}"
            )
            _console().print(f"  Ready tasks: {len(ready_tasks)}")
            _console().print(f"  First ready task: {ready_tasks[0].title}")

            await _core.start_run_mode(
                name=project.name,
                description=project.description,
                context={"project_id": project.id},
                continuous=continuous,
                time_limit=time_limit,
                mode_type="project",
            )

        asyncio.run(_async_project_start())

    @project_app.command("run")
    def project_run(
        spec_file: Path = typer.Argument(
            ..., help="Path to the project specification Markdown file.", exists=True
        ),
    ):
        """
        Run a complete project workflow from a specification file.

        This command will:
        1. Parse the spec file to create a project and tasks.
        2. Sequentially execute each task using the real agent system.
        3. Validate each task by running tests.
        4. Create a pull request for each validated task.
        """

        async def _async_run_workflow():
            _console().print(
                f"[bold blue]🐧 Starting project workflow from:[/bold blue] {spec_file}"
            )

            # --- Setup ---
            # Initialize core components to get the ProjectManager
            await _initialize_core_components_globally()
            project_manager = _core.project_manager

            # Use the real RunMode from the core instead of mocking
            run_mode = RunMode(_core)  # Pass the core instance

            # Initialize the rest of the managers
            if not GITHUB_REPOSITORY:
                _console().print(
                    "[red]Error: GITHUB_REPOSITORY is not configured in your .env or config.yml.[/red]"
                )
                raise typer.Exit(code=1)

            git_manager = GitManager(
                workspace_path=_workspace_path(),
                project_manager=project_manager,
                repo_owner_and_name=GITHUB_REPOSITORY,
            )
            validation_manager = ValidationManager(workspace_path=_workspace_path())
            task_executor = ProjectTaskExecutor(
                run_mode=run_mode, project_manager=project_manager
            )
            orchestrator = WorkflowOrchestrator(
                project_manager=project_manager,
                task_executor=task_executor,
                validation_manager=validation_manager,
                git_manager=git_manager,
            )

            # --- Act ---
            _console().print("\n[bold]1. Parsing project specification...[/bold]")
            try:
                spec_content = spec_file.read_text()
                parse_result = await parse_project_specification_from_markdown(
                    markdown_content=spec_content, project_manager=project_manager
                )
                if parse_result["status"] != "success":
                    _console().print(
                        f"[red]Error parsing spec file: {parse_result['message']}[/red]"
                    )
                    raise typer.Exit(code=1)

                project_id = parse_result["creation_result"]["project"]["id"]
                num_tasks = parse_result["creation_result"]["tasks_created"]
                _console().print(
                    f"[green]✓ Project '{parse_result['creation_result']['project']['name']}' created with {num_tasks} task(s).[/green]"
                )
            except Exception as e:
                _console().print(f"[red]Failed to read or parse spec file: {e}[/red]")
                raise typer.Exit(code=1)

            _console().print("\n[bold]2. Executing project tasks...[/bold]")
            task_number = 0
            while True:
                task_number += 1
                _console().print(f"\n--- Running Task {task_number}/{num_tasks} ---")
                workflow_result = await orchestrator.run_next_task(
                    project_id=project_id
                )

                if workflow_result is None:
                    _console().print("[bold green]✓ No more tasks to run.[/bold green]")
                    break

                _console().print(f"   Task: '{workflow_result['task_title']}'")
                if workflow_result.get("status") == "COMPLETED":
                    pr_url = workflow_result.get("pull_request", {}).get(
                        "pr_url", "N/A"
                    )
                    _console().print(
                        f"   [green]✓ Status: {workflow_result['status']}[/green]"
                    )
                    _console().print(f"   [green]✓ Pull Request: {pr_url}[/green]")
                else:
                    error_msg = workflow_result.get(
                        "error", "An unknown error occurred."
                    )
                    _console().print(
                        f"   [red]✗ Status: {workflow_result['status']}[/red]"
                    )
                    _console().print(f"   [red]✗ Reason: {error_msg}[/red]")
                    _console().print(
                        "[bold red]Workflow stopped due to failure.[/bold red]"
                    )
                    break

            _console().print("\n[bold blue]🐧 Project workflow finished.[/bold blue]")

        asyncio.run(_async_run_workflow())

    # Task Management Commands
    task_app = typer.Typer(help="Task management commands")
    project_app.add_typer(task_app, name="task")

    @task_app.command("create")
    def task_create(
        project_id: str = typer.Argument(..., help="Project ID"),
        title: str = typer.Argument(..., help="Task title"),
        description: Optional[str] = typer.Option(
            None, "--description", "-d", help="Task description"
        ),
        parent_task_id: Optional[str] = typer.Option(
            None, "--parent", "-p", help="Parent task ID"
        ),
        priority: int = typer.Option(1, "--priority", help="Task priority (1-5)"),
    ):
        """Create a new task in a project"""

        async def _async_task_create():
            _console().print(f"[bold cyan]🐧 Creating task:[/bold cyan] {title}")

            await _initialize_core_components_globally()

            if not _core or not _core.project_manager:
                _console().print("[red]Error: Project manager not available[/red]")
                raise typer.Exit(code=1)

            try:
                task = await create_task_service(
                    _core.project_manager,
                    project_id=project_id,
                    title=title,
                    description=description,
                    parent_task_id=parent_task_id,
                    priority=priority,
                )

                _console().print("[green]✓ Task created successfully![/green]")
                _console().print(f"  ID: {task.id}")
                _console().print(f"  Title: {task.title}")
                _console().print(f"  Status: {task.status.value}")
                _console().print(f"  Priority: {task.priority}")

            except Exception as e:
                _console().print(f"[red]Error creating task: {e}[/red]")
                raise typer.Exit(code=1)

        asyncio.run(_async_task_create())

    @task_app.command("list")
    def task_list(
        project_id: Optional[str] = typer.Argument(
            None, help="Project ID to filter tasks"
        ),
        status: Optional[str] = typer.Option(
            None,
            "--status",
            "-s",
            help="Filter by status (active, running, pending_review, completed, failed, blocked, cancelled)",
        ),
    ):
        """List tasks, optionally filtered by project or status"""

        async def _async_task_list():
            _console().print("[bold cyan]🐧 Tasks:[/bold cyan]")

            await _initialize_core_components_globally()

            if not _core or not _core.project_manager:
                _console().print("[red]Error: Project manager not available[/red]")
                raise typer.Exit(code=1)

            try:
                try:
                    tasks = await list_tasks_service(
                        _core.project_manager,
                        project_id=project_id,
                        status=status,
                    )
                except ValueError:
                    from penguin.project.models import TaskStatus

                    valid_options = ", ".join(item.value for item in TaskStatus)
                    _console().print(
                        f"[red]Invalid status: {status}. Valid options: {valid_options}[/red]"
                    )
                    raise typer.Exit(code=1)

                if not tasks:
                    filter_desc = ""
                    if project_id:
                        filter_desc += f" in project {project_id[:8]}"
                    if status:
                        filter_desc += f" with status {status}"
                    _console().print(f"[yellow]No tasks found{filter_desc}[/yellow]")
                    return

                from rich.table import Table

                table = Table(show_header=True, header_style="bold magenta")
                table.add_column("ID", style="dim", width=8)
                table.add_column("Project", style="cyan", width=8)
                table.add_column("Title", style="white")
                table.add_column("Status", style="green")
                table.add_column("Priority", style="yellow", width=8)
                table.add_column("Created", style="dim")

                for task in tasks:
                    table.add_row(
                        task.id[:8],
                        task.project_id[:8],
                        task.title,
                        task.status.value,
                        str(task.priority),
                        task.created_at[:16]
                        if task.created_at
                        else "Unknown",  # created_at is ISO string, take first 16 chars
                    )

                _console().print(table)

            except typer.Exit:
                raise
            except Exception as e:
                _console().print(f"[red]Error listing tasks: {e}[/red]")
                raise typer.Exit(code=1)

        asyncio.run(_async_task_list())

    @task_app.command("start")
    def task_start(task_id: str = typer.Argument(..., help="Task ID to start")):
        """Start a task by moving it into the active state."""

        async def _async_task_start():
            await _initialize_core_components_globally()

            if not _core or not _core.project_manager:
                _console().print("[red]Error: Project manager not available[/red]")
                raise typer.Exit(code=1)

            try:
                try:
                    task, updated_task = await start_task_service(
                        _core.project_manager, task_id
                    )
                except TaskNotFoundError:
                    _console().print(
                        f"[red]Error: Task with ID '{task_id}' not found[/red]"
                    )
                    raise typer.Exit(code=1)
                except TaskMutationError:
                    _console().print("[red]Failed to start task[/red]")
                    raise typer.Exit(code=1)

                _console().print(
                    f"[green]✓ Task '{task.title}' moved to active state[/green]"
                )
                _console().print(f"  Status: {updated_task.status.value}")

            except Exception as e:
                _console().print(f"[red]Error starting task: {e}[/red]")
                raise typer.Exit(code=1)

        asyncio.run(_async_task_start())

    @task_app.command("complete")
    def task_complete(task_id: str = typer.Argument(..., help="Task ID to complete")):
        """Approve a task that is pending review and mark it completed."""

        async def _async_task_complete():
            await _initialize_core_components_globally()

            if not _core or not _core.project_manager:
                _console().print("[red]Error: Project manager not available[/red]")
                raise typer.Exit(code=1)

            try:
                try:
                    task, updated_task, already_completed = await complete_task_service(
                        _core.project_manager, task_id
                    )
                except TaskNotFoundError:
                    _console().print(
                        f"[red]Error: Task with ID '{task_id}' not found[/red]"
                    )
                    raise typer.Exit(code=1)
                except InvalidTaskStateError:
                    _console().print(
                        "[red]Task must be in pending_review before it can be approved[/red]"
                    )
                    raise typer.Exit(code=1)
                except TaskMutationError:
                    _console().print("[red]Failed to approve task[/red]")
                    raise typer.Exit(code=1)

                if already_completed:
                    _console().print(
                        f"[yellow]Task '{task.title}' is already completed[/yellow]"
                    )

                _console().print(f"[green]✓ Task '{task.title}' approved[/green]")
                _console().print(f"  Status: {updated_task.status.value}")

            except Exception as e:
                _console().print(f"[red]Error completing task: {e}[/red]")
                raise typer.Exit(code=1)

        asyncio.run(_async_task_complete())

    @task_app.command("delete")
    def task_delete(
        task_id: str = typer.Argument(..., help="Task ID to delete"),
        force: bool = typer.Option(
            False, "--force", "-f", help="Force delete without confirmation"
        ),
    ):
        """Delete a task"""

        async def _async_task_delete():
            await _initialize_core_components_globally()

            if not _core or not _core.project_manager:
                _console().print("[red]Error: Project manager not available[/red]")
                raise typer.Exit(code=1)

            try:
                task = await _core.project_manager.get_task_async(task_id)
                if not task:
                    _console().print(
                        f"[red]Error: Task with ID '{task_id}' not found[/red]"
                    )
                    raise typer.Exit(code=1)

                if not force:
                    confirm = typer.confirm(
                        f"Are you sure you want to delete task '{task.title}' ({task_id[:8]})?"
                    )
                    if not confirm:
                        _console().print("[yellow]Operation cancelled[/yellow]")
                        return

                try:
                    await delete_task_service(_core.project_manager, task_id)
                except TaskMutationError:
                    _console().print("[red]Failed to delete task[/red]")
                    raise typer.Exit(code=1)
                _console().print(
                    f"[green]✓ Task '{task.title}' deleted successfully[/green]"
                )

            except Exception as e:
                _console().print(f"[red]Error deleting task: {e}[/red]")
                raise typer.Exit(code=1)

        asyncio.run(_async_task_delete())

    # Duplicate chat command was deprecated; keeping stub commented out to avoid Typer double-registration
    # @app.command()
    # async def chat(): # Removed model, workspace, no_streaming options
    #     """(Deprecated duplicate)"""
    #     return

    # Interactive application lives in penguin.cli.interactive; imported above.

    return {
        "task_app": task_app,
        "project_init": project_init,
        "project_create": project_create,
        "project_list": project_list,
        "project_delete": project_delete,
        "project_start": project_start,
        "project_run": project_run,
        "task_create": task_create,
        "task_list": task_list,
        "task_start": task_start,
        "task_complete": task_complete,
        "task_delete": task_delete,
        "_resolve_project_identifier_or_exit": _resolve_project_identifier_or_exit,
        "_delete_project_and_tasks_async": _delete_project_and_tasks_async,
    }
