# Implementing a parser for the actions that the AI returns in its response.
# This is a simple parser that can be extended to support more complex actions.
# The parser is based on the idea of "action types" and "parameters" that are returned in the AI response.

# Inspired by the CodeAct paper: https://arxiv.org/abs/2402.01030
# CodeAct Github: https://github.com/xingyaoww/code-act

import asyncio
import logging
import re
from datetime import datetime
from enum import Enum
from html import unescape
from typing import List, Dict, Any
import base64
from penguin.local_task.manager import ProjectManager
from penguin.tools import ToolManager
from penguin.utils.process_manager import ProcessManager
from penguin.system.conversation import MessageCategory
from penguin.tools.browser_tools import BrowserScreenshotTool, browser_manager
import os
logger = logging.getLogger(__name__)


class ActionType(Enum):
    # READ = "read"
    # WRITE = "write"
    EXECUTE = "execute"
    EXECUTE_COMMAND = "execute_command"
    SEARCH = "search"
    # CREATE_FILE = "create_file"
    # CREATE_FOLDER = "create_folder"
    # LIST_FILES = "list_files"
    # LIST_FOLDERS = "list_folders"
    # GET_FILE_MAP = "get_file_map"
    # LINT = "lint"
    MEMORY_SEARCH = "memory_search"
    ADD_DECLARATIVE_NOTE = "add_declarative_note"
    # TASK_CREATE = "task_create"
    # TASK_UPDATE = "task_update"
    # TASK_COMPLETE = "task_complete"
    # TASK_LIST = "task_list"
    # PROJECT_CREATE = "project_create"
    # PROJECT_UPDATE = "project_update"
    # PROJECT_COMPLETE = "project_complete"
    # PROJECT_LIST = "project_list"
    # SUBTASK_ADD = "subtask_add"
    # TODO: add subtask_update, subtask_complete, subtask_list
    # TASK_DETAILS = "task_details"
    # PROJECT_DETAILS = "project_details"
    # WORKFLOW_ANALYZE = "workflow_analyze"
    ADD_SUMMARY_NOTE = "add_summary_note"
    PERPLEXITY_SEARCH = "perplexity_search"
    # REPL, iPython, shell, bash, zsh, networking, file_management, task management, etc.
    # TODO: Add more actions as needed
    PROCESS_START = "process_start"
    PROCESS_STOP = "process_stop"
    PROCESS_STATUS = "process_status"
    PROCESS_LIST = "process_list"
    PROCESS_ENTER = "process_enter"
    PROCESS_SEND = "process_send"
    PROCESS_EXIT = "process_exit"
    WORKSPACE_SEARCH = "workspace_search"
    # Task Management Actions
    TASK_CREATE = "task_create"
    TASK_UPDATE = "task_update"
    TASK_COMPLETE = "task_complete"
    TASK_DELETE = "task_delete"
    TASK_LIST = "task_list"
    TASK_DISPLAY = "task_display"
    PROJECT_CREATE = "project_create"
    PROJECT_UPDATE = "project_update"
    PROJECT_DELETE = "project_delete"
    PROJECT_LIST = "project_list"
    PROJECT_DISPLAY = "project_display"
    DEPENDENCY_DISPLAY = "dependency_display"
    ANALYZE_CODEBASE = "analyze_codebase"
    REINDEX_WORKSPACE = "reindex_workspace"
    # Browser actions
    BROWSER_NAVIGATE = "browser_navigate"
    BROWSER_INTERACT = "browser_interact"
    BROWSER_SCREENSHOT = "browser_screenshot"
    # PyDoll browser actions
    PYDOLL_BROWSER_NAVIGATE = "pydoll_browser_navigate"
    PYDOLL_BROWSER_INTERACT = "pydoll_browser_interact"
    PYDOLL_BROWSER_SCREENSHOT = "pydoll_browser_screenshot"
    # PyDoll debug toggle
    PYDOLL_DEBUG_TOGGLE = "pydoll_debug_toggle"


class CodeActAction:
    def __init__(self, action_type, params):
        self.action_type = action_type
        self.params = params


def parse_action(content: str) -> List[CodeActAction]:
    """Parse actions from content using regex pattern matching.
    
    Args:
        content: The string content to parse for actions
        
    Returns:
        A list of CodeActAction objects, empty if no actions found
    """
    # Remove string-based validation
    if not content.strip():
        return []
    
    # Check for common action tag patterns - using the enum values directly to ensure only valid actions are detected
    action_tag_pattern = "|".join([action_type.value for action_type in ActionType])
    action_tag_regex = f"<({action_tag_pattern})>.*?</\\1>"  # Match complete tag pairs only
    
    if not re.search(action_tag_regex, content, re.DOTALL | re.IGNORECASE):
        # No properly formed action tags found
        logger.debug("No properly formed action tags found in content")
        return []
        
    # Extract only the AI's response part
    try:
        # Use more specific pattern matching to only extract valid action types
        pattern = f"<({action_tag_pattern})>(.*?)</\\1>"
        matches = re.finditer(pattern, content, re.DOTALL)

        actions = []  # Initialize the actions list
        
        match_found = False
        for match in matches:
            match_found = True
            action_type = match.group(1).lower()
            params = unescape(match.group(2).strip())
            
            # Verify this is a valid action type
            try:
                action_type_enum = ActionType[action_type.upper()]
                action = CodeActAction(action_type_enum, params)
                actions.append(action)
                logger.debug(f"Found valid action: {action_type}")
            except KeyError:
                # This shouldn't happen with our updated regex, but just in case
                logger.warning(f"Unrecognized action type: {action_type}")
                pass
        
        if not match_found:
            logger.debug("No actions matched in content despite initial regex check")
        
        return actions
    except Exception as e:
        logger.error(f"Error parsing actions: {str(e)}", exc_info=True)
        return []


class ActionExecutor:
    def __init__(self, tool_manager: ToolManager, task_manager: ProjectManager, conversation_system=None):
        self.tool_manager = tool_manager
        self.task_manager = task_manager
        self.process_manager = ProcessManager()
        self.current_process = None
        self.conversation_system = conversation_system
        # No direct initialization of expensive tools, we'll use tool_manager's properties

    async def execute_action(self, action: CodeActAction) -> str:
        logger.debug(f"Attempting to execute action: {action.action_type.value}")
        action_map = {
            # ActionType.READ: lambda params: self.tool_manager.execute_tool("read_file", {"path": params}),
            # ActionType.WRITE: self._write_file,
            ActionType.EXECUTE: self._execute_code,
            ActionType.EXECUTE_COMMAND: self._execute_command, #TODO: FULLY IMPLEMENT THIS
            ActionType.SEARCH: lambda params: self.tool_manager.execute_tool(
                "grep_search", {"pattern": params}
            ),
            # ActionType.CREATE_FILE: self._create_file,
            # ActionType.CREATE_FOLDER: lambda params: self.tool_manager.execute_tool("create_folder", {"path": params}),
            # ActionType.LIST_FILES: lambda params: self.tool_manager.execute_tool("list_files", {"directory": params}),
            # ActionType.LIST_FOLDERS: lambda params: self.tool_manager.execute_tool("list_files", {"directory": params}),
            # ActionType.GET_FILE_MAP: lambda params: self.tool_manager.execute_tool("get_file_map", {"directory": params}),
            # ActionType.LINT: self._lint_python,
            ActionType.MEMORY_SEARCH: self._memory_search,
            ActionType.ADD_DECLARATIVE_NOTE: self._add_declarative_note,
            # ActionType.TASK_CREATE: self._execute_task_create,
            # ActionType.TASK_UPDATE: self._execute_task_update,
            # ActionType.TASK_COMPLETE: self._execute_task_complete,
            # ActionType.TASK_LIST: lambda params: list_tasks(self.task_manager),
            # ActionType.PROJECT_CREATE: self._execute_project_create,
            # ActionType.PROJECT_UPDATE: lambda params: update_task(self.task_manager, *params.split(':', 1)),
            # ActionType.PROJECT_COMPLETE: self._execute_project_complete,
            # ActionType.PROJECT_LIST: lambda params: list_tasks(self.task_manager),
            # ActionType.SUBTASK_ADD: self._execute_subtask_add,
            # ActionType.TASK_DETAILS: lambda params: get_task_details(self.task_manager, params),
            # ActionType.PROJECT_DETAILS: lambda params: self.task_manager.get_project_details(params),
            # ActionType.WORKFLOW_ANALYZE: lambda params: self.task_manager.analyze_workflow(),
            ActionType.ADD_SUMMARY_NOTE: self._add_summary_note,
            ActionType.PERPLEXITY_SEARCH: self._perplexity_search,
            ActionType.PROCESS_START: self._process_start,
            ActionType.PROCESS_STOP: self._process_stop,
            ActionType.PROCESS_STATUS: self._process_status,
            ActionType.PROCESS_LIST: self._process_list,
            ActionType.PROCESS_ENTER: self._process_enter,
            ActionType.PROCESS_SEND: self._process_send,
            ActionType.PROCESS_EXIT: self._process_exit,
            ActionType.WORKSPACE_SEARCH: self._workspace_search,
            # Project management handlers
            ActionType.PROJECT_CREATE: self._project_create,
            ActionType.PROJECT_LIST: self._project_list,
            ActionType.PROJECT_UPDATE: self._project_update,
            ActionType.PROJECT_DELETE: self._project_delete,
            ActionType.PROJECT_DISPLAY: self._project_display,
            # Task management handlers
            ActionType.TASK_CREATE: self._task_create,
            ActionType.TASK_UPDATE: self._task_update,
            ActionType.TASK_COMPLETE: self._task_complete,
            ActionType.TASK_DELETE: self._task_delete,
            ActionType.TASK_LIST: self._task_list,
            ActionType.TASK_DISPLAY: self._task_display,
            ActionType.DEPENDENCY_DISPLAY: self._dependency_display,
            ActionType.ANALYZE_CODEBASE: self._analyze_codebase,
            ActionType.REINDEX_WORKSPACE: self._reindex_workspace,
            # Browser actions
            ActionType.BROWSER_NAVIGATE: self._browser_navigate,
            ActionType.BROWSER_INTERACT: self._browser_interact,
            ActionType.BROWSER_SCREENSHOT: self._browser_screenshot,
            # PyDoll browser actions
            ActionType.PYDOLL_BROWSER_NAVIGATE: self._pydoll_browser_navigate,
            ActionType.PYDOLL_BROWSER_INTERACT: self._pydoll_browser_interact,
            ActionType.PYDOLL_BROWSER_SCREENSHOT: self._pydoll_browser_screenshot,
            # PyDoll debug toggle
            ActionType.PYDOLL_DEBUG_TOGGLE: self._pydoll_debug_toggle
        }

        try:
            if action.action_type not in action_map:
                logger.warning(f"Unknown action type: {action.action_type.value}")
                return f"Unknown action type: {action.action_type.value}"

            handler = action_map[action.action_type]
            logger.debug(f"Handler for action {action.action_type.value}: {handler}")

            if asyncio.iscoroutinefunction(handler):
                logger.debug(f"Executing async handler for {action.action_type.value}")
                result = await handler(action.params)
            else:
                logger.debug(f"Executing sync handler for {action.action_type.value}")
                result = handler(action.params)
                if asyncio.iscoroutine(result):
                    result = await result

            logger.info(f"Action {action.action_type.value} executed successfully")
            return result
        except Exception as e:
            error_message = (
                f"Error executing action {action.action_type.value}: {str(e)}"
            )
            logger.error(error_message, exc_info=True)
            return error_message

    # def _write_file(self, params: str) -> str:
    #     path, content = params.split(':', 1)
    #     return self.tool_manager.execute_tool("write_to_file", {"path": path.strip(), "content": content.strip()})

    # def _create_file(self, params: str) -> str:
    #     path, content = params.split(':', 1)
    #     return self.tool_manager.execute_tool("create_file", {"path": path.strip(), "content": content.strip()})

    def _execute_code(self, params: str) -> str:
        logger.debug(f"Executing code: {params}")
        return self.tool_manager.execute_code(params)

    def _execute_command(self, params: str) -> str:
        """Execute a shell command using the tool manager."""
        logger.debug(f"Executing command: {params}")
        return self.tool_manager.execute_tool("execute_command", {"command": params})

    # def _lint_python(self, params: str) -> str:
    #     parts = params.split(':', 1)
    #     if len(parts) == 2:
    #         target, is_file = parts[0].strip(), parts[1].strip().lower() == 'true'
    #     else:
    #         target, is_file = params.strip(), False

    #     # Use the current working directory to resolve the file path
    #     if is_file:
    #         target = str(Path.cwd() / target)

    # return self.tool_manager.execute_tool("lint_python", {"target": target, "is_file": is_file})

    # def _memory_search(self, params: str) -> str:
    #     query, k = params.split(":", 1) if ":" in params else (params, "5")
    #     return self.tool_manager.execute_tool(
    #         "memory_search", {"query": query.strip(), "k": int(k.strip())}
    #     )

    def _add_declarative_note(self, params: str) -> str:
        category, content = params.split(":", 1)
        return self.tool_manager.execute_tool(
            "add_declarative_note",
            {"category": category.strip(), "content": content.strip()},
        )

    def _create_folder(self, params: str) -> str:
        return self.tool_manager.execute_tool("create_folder", {"path": params})

    def _add_summary_note(self, params: str) -> str:
        # If there's no explicit category, use a default one
        if ":" not in params:
            category = "general"
            content = params.strip()
        else:
            category, content = params.split(":", 1)
            category = category.strip()
            content = content.strip()

        return self.tool_manager.add_summary_note(category, content)

    def _perplexity_search(self, params: str) -> str:
        parts = params.split(":", 1)
        if len(parts) == 2:
            query, max_results = parts[0].strip(), int(parts[1].strip())
        else:
            query, max_results = params.strip(), 5

        results = self.tool_manager.execute_tool(
            "perplexity_search", {"query": query, "max_results": max_results}
        )

        # The results are already formatted as a string by the PerplexityProvider
        return results

    async def _process_start(self, params: str) -> str:
        logger.debug(f"Starting process with params: {params}")
        name, command = params.split(":", 1)
        return await self.process_manager.start_process(name.strip(), command.strip())

    async def _process_stop(self, params: str) -> str:
        return await self.process_manager.stop_process(params.strip())

    async def _process_status(self, params: str) -> str:
        return await self.process_manager.get_process_status(params.strip())

    async def _process_list(self, params: str) -> str:
        processes = await self.process_manager.list_processes()
        return "\n".join([f"{name}: {status}" for name, status in processes.items()])

    async def _process_enter(self, params: str) -> str:
        name = params.strip()
        reader = await self.process_manager.enter_process(name)
        if reader:
            self.current_process = name
            initial_output = await reader.read(1024)
            return (
                f"Entered process '{name}'. Initial output:\n{initial_output.decode()}"
            )
        return f"Failed to enter process '{name}'"

    async def _process_send(self, params: str) -> str:
        if not self.current_process:
            return "Not currently in any process"
        return await self.process_manager.send_command(
            self.current_process, params.strip()
        )

    async def _process_exit(self, params: str) -> str:
        if not self.current_process:
            return "Not currently in any process"
        result = await self.process_manager.exit_process(self.current_process)
        self.current_process = None
        return result

    def _workspace_search(self, params: str) -> str:
        parts = params.split(":", 1)
        if len(parts) == 2:
            query, max_results = parts[0].strip(), int(parts[1].strip())
        else:
            query, max_results = params.strip(), 5

        return self.tool_manager.execute_tool(
            "workspace_search", {"query": query, "max_results": max_results}
        )

    async def _memory_search(self, params: str) -> str:
        """
        Parse and execute memory search command
        Format: query:max_results:memory_type:categories:date_after:date_before
        Example: "project planning:5:logs:planning,projects:2024-01-01:2024-03-01"
        """
        try:
            parts = params.split(":")
            query = parts[0].strip()

            # Parse optional parameters
            max_results = int(parts[1]) if len(parts) > 1 and parts[1].strip() else 5
            memory_type = (
                parts[2].strip() if len(parts) > 2 and parts[2].strip() else None
            )
            categories = (
                parts[3].strip().split(",")
                if len(parts) > 3 and parts[3].strip()
                else None
            )

            # Use the tool_manager's memory_search method which will access the lazily loaded memory_searcher
            json_results = await self.tool_manager.perform_memory_search(
                query=query,
                k=max_results,
                memory_type=memory_type,
                categories=categories,
            )

            # Parse the JSON string returned by perform_memory_search
            try:
                import json
                parsed_results = json.loads(json_results)
                
                # Handle error responses
                if isinstance(parsed_results, dict) and "error" in parsed_results:
                    return f"Memory search error: {parsed_results['error']}"
                
                # Handle "no results" response
                if isinstance(parsed_results, dict) and "result" in parsed_results:
                    return parsed_results["result"]
                
                # Handle actual search results
                if isinstance(parsed_results, list):
                    results = parsed_results
                else:
                    return "Unexpected response format from memory search."
                    
            except json.JSONDecodeError:
                return f"Error parsing memory search results: {json_results}"

            # Format results for display
            if not results:
                return "No results found."

            formatted_results = []
            for i, result in enumerate(results, 1):
                # Fix metadata field names to match actual result structure
                metadata = result.get('metadata', {})
                file_path = metadata.get('path', metadata.get('file_path', 'Unknown'))
                file_type = metadata.get('file_type', metadata.get('memory_type', 'Unknown'))
                categories = result.get('categories', metadata.get('categories', 'None'))
                
                formatted_results.append(
                    f"\n{i}. From: {file_path}"
                )
                formatted_results.append(
                    f"   Type: {file_type}"
                )
                formatted_results.append(
                    f"   Categories: {categories}"
                )
                formatted_results.append(f"   Score: {result.get('score', result.get('relevance', 0)):.2f}")
                
                # Enhanced preview for conversation messages
                if file_type == 'conversation_message':
                    role = metadata.get('message_role', 'unknown')
                    timestamp = metadata.get('timestamp', '')
                    session_id = metadata.get('session_id', 'unknown')
                    
                    formatted_results.append(f"   Role: {role}")
                    if timestamp:
                        formatted_results.append(f"   Time: {timestamp[:19]}")  # YYYY-MM-DDTHH:MM:SS
                    formatted_results.append(f"   Session: {session_id}")
                    formatted_results.append("   Message:")
                    
                    # Get content preview with conversation context
                    content = result.get('content', result.get('preview', 'No preview available'))
                    # For conversation messages, show more content (up to 300 characters)
                    preview = content[:300] + "..." if len(content) > 300 else content
                    # Indent the content for better readability
                    indented_preview = "\n".join(f"   > {line}" for line in preview.split('\n'))
                    formatted_results.append(indented_preview)
                else:
                    formatted_results.append("   Preview:")
                    # Get content preview, limiting to 200 characters
                    content = result.get('content', result.get('preview', 'No preview available'))
                    preview = content[:200] + "..." if len(content) > 200 else content
                    formatted_results.append(f"   {preview}")
                
                formatted_results.append("")

            return "\n".join(formatted_results)

        except Exception as e:
            return f"Error executing memory search: {str(e)}"

    async def _memory_index(self, params: str) -> str:
        """Index all memory files"""
        try:
            return self.tool_manager.index_memory()
        except Exception as e:
            return f"Error indexing memory: {str(e)}"

    def _project_create(self, params: str) -> str:
        """Create a new project. Format: name:description"""
        try:
            name, description = params.split(":", 1)
            project = self.task_manager.create(name.strip(), description.strip())
            return f"Project created: {project.name}"
        except Exception as e:
            return f"Error creating project: {str(e)}"

    def _project_list(self, params: str) -> str:
        """List all projects"""
        try:
            projects = (
                self.task_manager.projects.values()
            )  # Access the projects dict directly
            if not projects:
                return "No projects found."
            return "\n".join([f"- {p.name}: {p.description}" for p in projects])
        except Exception as e:
            return f"Error listing projects: {str(e)}"

    def _project_update(self, params: str) -> str:
        """Update project status. Format: name:description"""
        try:
            name, description = params.split(":", 1)
            self.task_manager.update_status(name.strip(), description.strip())
            return f"Project '{name}' updated successfully"
        except Exception as e:
            return f"Error updating project: {str(e)}"

    def _project_delete(self, params: str) -> str:
        """Delete a project. Format: name"""
        try:
            self.task_manager.delete(params.strip())
            return f"Project '{params}' deleted successfully"
        except Exception as e:
            return f"Error deleting project: {str(e)}"

    def _project_display(self, params: str) -> str:
        """Display project details. Format: name"""
        try:
            output = self.task_manager.display(params.strip())
            return output
        except Exception as e:
            return f"Error displaying project: {str(e)}"

    def _task_create(self, params: str) -> str:
        """Create a new task. Format: name:description[:project_name]"""
        try:
            parts = params.split(":", 2)
            if len(parts) < 2:
                return "Error: Invalid task format. Use name:description[:project_name]"
            name, description = parts[0:2]
            project_name = parts[2].strip() if len(parts) > 2 else None
            response = self.task_manager.create_task(
                name.strip(), description.strip(), project_name
            )

            if isinstance(response, dict) and "result" in response:
                return response["result"]
            return f"Task created: {name}"
        except Exception as e:
            return f"Error creating task: {str(e)}"

    def _task_update(self, params: str) -> str:
        """Update task status. Format: name:description"""
        try:
            name, description = params.split(":", 1)
            self.task_manager.update_status(name.strip(), description.strip())
            return f"Task '{name}' updated successfully"
        except Exception as e:
            return f"Error updating task: {str(e)}"

    def _task_complete(self, params: str) -> str:
        """Complete a task. Format: name"""
        try:
            self.task_manager.complete(params.strip())
            return f"Task '{params}' completed successfully"
        except Exception as e:
            return f"Error completing task: {str(e)}"

    def _task_delete(self, params: str) -> str:
        """Delete a task. Format: name"""
        try:
            self.task_manager.delete(params.strip())
            return f"Task '{params}' deleted successfully"
        except Exception as e:
            return f"Error deleting task: {str(e)}"

    def _task_list(self, params: str) -> str:
        """List tasks. Format: project_name(optional)"""
        try:
            tasks = []
            if params.strip():
                # List tasks for specific project
                project = self.task_manager._find_project_by_name(params.strip())
                if not project:
                    return f"Project '{params}' not found."
                tasks = list(project.tasks.values())
            else:
                # List ALL tasks (both project and independent)
                tasks = list(self.task_manager.independent_tasks.values())
                # Also get project tasks
                for project in self.task_manager.projects.values():
                    tasks.extend(project.tasks.values())

            if not tasks:
                return "No tasks found."

            # Format tasks into a readable table-like string
            formatted_tasks = []
            for task in tasks:
                status_icon = {"active": "🔵", "completed": "✅", "archived": "📦"}.get(
                    task.status, "❓"
                )

                priority_icon = {1: "🔴", 2: "🟡", 3: "🟢"}.get(task.priority, "⚪")

                task_line = [
                    f"{priority_icon} {status_icon} {task.title}",
                    f"    Status: {task.status}",
                    f"    Progress: {task.progress}%",
                    f"    Description: {task.description}",
                ]

                if task.tags:
                    task_line.append(
                        f"    Tags: {', '.join(f'#{tag}' for tag in task.tags)}"
                    )
                if task.due_date:
                    task_line.append(f"    Due: {task.due_date}")

                formatted_tasks.append("\n".join(task_line))

            return "\n\n".join(formatted_tasks)

        except Exception as e:
            logger.error(f"Error in _task_list: {str(e)}", exc_info=True)
            return f"Error listing tasks: {str(e)}"

    def _task_display(self, params: str) -> str:
        """Display task details. Format: name"""
        try:
            output = self.task_manager.display(params.strip())
            return output
        except Exception as e:
            return f"Error displaying task: {str(e)}"

    def _dependency_display(self, params: str) -> str:
        """Display dependencies for a task or project"""
        try:
            return self.task_manager.display_dependencies(params.strip())
        except Exception as e:
            return f"Error displaying dependencies: {str(e)}"

    def _context_get(self, params: str) -> str:
        """Get context for a project or task. Format: project_name/task_name"""
        try:
            # First try to find project
            project = self.task_manager._find_project_by_name(params)
            if project:
                # List all context files in project's context directory
                context_files = list(project.context_path.glob("*.md"))
                if not context_files:
                    return "No context files found for project."

                results = [f"Context for project '{params}':"]
                for cf in context_files:
                    with cf.open("r") as f:
                        content = f.read()
                    results.append(f"\n--- {cf.name} ---\n{content}")
                return "\n".join(results)

            # If not found, try to find task
            task = self.task_manager._find_task_by_name(params)
            if task:
                if not task.metadata.get("context"):
                    return f"No context found for task '{params}'"
                return f"Context for task '{params}':\n{task.metadata['context']}"

            return f"No project or task found with name: {params}"

        except Exception as e:
            return f"Error getting context: {str(e)}"

    def _context_add(self, params: str) -> str:
        """Add context to project/task. Format: name:content[:type]"""
        try:
            parts = params.split(":", 2)
            if len(parts) < 2:
                return "Error: Invalid format. Use name:content[:type]"

            name, content = parts[0:2]
            context_type = parts[2] if len(parts) > 2 else "notes"

            # Try project first
            project = self.task_manager._find_project_by_name(name)
            if project:
                context_file = self.task_manager.add_context(
                    project.id, content, context_type
                )
                return f"Added context to project '{name}': {context_file}"

            # Try task
            task = self.task_manager._find_task_by_name(name)
            if task:
                if "context" not in task.metadata:
                    task.metadata["context"] = []
                task.metadata["context"].append(
                    {
                        "type": context_type,
                        "content": content,
                        "added_at": datetime.now().isoformat(),
                    }
                )
                return f"Added context to task '{name}'"

            return f"No project or task found with name: {name}"

        except Exception as e:
            return f"Error adding context: {str(e)}"

    async def _browser_interact(self, params: str) -> str:
        """Interact with browser elements. Format: action:selector:text"""
        parts = params.split(':', 2)
        if len(parts) < 2:
            return "Error: Invalid format. Use action:selector[:text]"
        
        action = parts[0].strip()
        selector = parts[1].strip()
        text = parts[2].strip() if len(parts) > 2 else None
        
        if action not in ['click', 'input', 'submit']:
            return f"Error: Invalid action '{action}'. Use click, input, or submit."
        
        return await self.tool_manager.execute_browser_interact(action, selector, text)

    async def _browser_screenshot(self, params: str) -> str:
        try:
            tool = BrowserScreenshotTool()
            result = await tool.execute()
            
            if "filepath" in result:
                # Extract description from params or use default
                description = params.strip() if params else "What can you see in this screenshot?"
                
                # Create multimodal content in the same format as the /image command result
                multimodal_content = [
                    {"type": "text", "text": description},
                    {"type": "image_url", "image_path": result["filepath"]}
                ]
                
                # Add as a user message (matching how /image adds to conversation)
                self.conversation_system.add_message(
                    role="user",
                    content=multimodal_content,
                    category=MessageCategory.DIALOG
                )
                
                return f"Screenshot saved to {result['filepath']} and added to conversation"
            else:
                return result.get("error", "Failed to capture screenshot")
        except Exception as e:
            return f"Error taking screenshot: {str(e)}"

    async def _browser_navigate(self, params: str) -> str:
        if not await browser_manager.initialize():
            return "Failed to initialize browser"
        return await browser_manager.navigate_to(params)

    async def _pydoll_browser_navigate(self, params: str) -> str:
        """Navigate to a URL using PyDoll browser."""
        try:
            from penguin.tools.pydoll_tools import pydoll_browser_manager
            
            if not await pydoll_browser_manager.initialize(headless=False):
                return "Failed to initialize PyDoll browser"
            
            # Get a page and navigate to the URL
            page = await pydoll_browser_manager.get_page()
            await page.go_to(params.strip())
            
            return f"Successfully navigated to {params.strip()} using PyDoll browser"
        except Exception as e:
            error_message = f"Error navigating with PyDoll browser: {str(e)}"
            logger.error(error_message)
            return error_message

    async def _pydoll_browser_interact(self, params: str) -> str:
        """Interact with browser elements using PyDoll. Format: action:selector[:selector_type][:text]"""
        try:
            from penguin.tools.pydoll_tools import PyDollBrowserInteractionTool
            
            parts = params.split(':', 3)
            if len(parts) < 2:
                return "Error: Invalid format. Use action:selector[:selector_type][:text]"
            
            action = parts[0].strip()
            selector = parts[1].strip()
            selector_type = parts[2].strip() if len(parts) > 2 and parts[2].strip() else "css"
            text = parts[3].strip() if len(parts) > 3 else None
            
            if action not in ["click", "input", "submit"]:
                return f"Error: Invalid action '{action}'. Use click, input, or submit."
            
            # Create and execute the tool
            tool = PyDollBrowserInteractionTool()
            result = await tool.execute(action, selector, selector_type, text)
            return result
        except Exception as e:
            error_message = f"Error interacting with PyDoll browser: {str(e)}"
            logger.error(error_message)
            return error_message

    async def _pydoll_browser_screenshot(self, params: str) -> str:
        """Take a screenshot using PyDoll browser."""
        try:
            from penguin.tools.pydoll_tools import PyDollBrowserScreenshotTool
            
            # Execute the screenshot tool
            tool = PyDollBrowserScreenshotTool()
            result = await tool.execute()
            
            # Debug the result
            logger.info(f"PyDoll screenshot result: {result}")
            
            if "filepath" in result and os.path.exists(result["filepath"]):
                # Extract description from params or use default
                description = params.strip() if params else "What can you see in this PyDoll screenshot?"
                
                # If conversation system is available, add to it as multimodal content
                if hasattr(self, 'conversation_system') and self.conversation_system:
                    # Create multimodal content in the same format as the /image command result
                    multimodal_content = [
                        {"type": "text", "text": description},
                        {"type": "image_url", "image_path": result["filepath"]}
                    ]
                    
                    logger.info(f"Adding PyDoll screenshot to conversation: {multimodal_content}")
                    
                    # Add as a user message (matching how /image adds to conversation)
                    self.conversation_system.add_message(
                        role="user",
                        content=multimodal_content,
                        category=MessageCategory.DIALOG
                    )
                    
                    return f"PyDoll screenshot saved to {result['filepath']} and added to conversation"
                else:
                    logger.warning("Conversation system not available, screenshot not added to conversation")
                    return f"PyDoll screenshot saved to {result['filepath']} but not added to conversation (conversation system not available)"
            else:
                error_msg = result.get("error", "Failed to capture PyDoll screenshot or file not found")
                logger.error(f"PyDoll screenshot error: {error_msg}")
                return error_msg
        except Exception as e:
            error_message = f"Error taking PyDoll screenshot: {str(e)}"
            logger.error(error_message, exc_info=True)
            return error_message

    async def _pydoll_debug_toggle(self, params: str) -> str:
        """Toggle PyDoll debug mode. Format: [on|off] or empty to toggle"""
        try:
            from penguin.tools.pydoll_tools import pydoll_debug_toggle
            
            if params.strip().lower() == "on":
                enabled = True
            elif params.strip().lower() == "off":
                enabled = False
            else:
                # Toggle current state if no specific instruction
                enabled = None
                
            new_state = await pydoll_debug_toggle(enabled)
            return f"PyDoll debug mode is now {'enabled' if new_state else 'disabled'}"
        except Exception as e:
            error_message = f"Error toggling PyDoll debug mode: {str(e)}"
            logger.error(error_message)
            return error_message

    async def _analyze_codebase(self, params: str) -> str:
        """Invoke analyze_codebase tool. Format: directory:analysis_type:include_external"""
        parts = params.split(":")
        directory = parts[0].strip() if parts and parts[0].strip() else ""
        analysis_type = parts[1].strip() if len(parts) > 1 and parts[1].strip() else "all"
        include_external = parts[2].strip().lower() == "true" if len(parts) > 2 else False
        return self.tool_manager.execute_tool(
            "analyze_codebase",
            {
                "directory": directory,
                "analysis_type": analysis_type,
                "include_external": include_external,
            },
        )

    async def _reindex_workspace(self, params: str) -> str:
        """Invoke reindex_workspace tool. Format: directory:force_full"""
        parts = params.split(":")
        directory = parts[0].strip() if parts and parts[0].strip() else ""
        force_full = parts[1].strip().lower() == "true" if len(parts) > 1 else False
        return self.tool_manager.execute_tool(
            "reindex_workspace",
            {
                "directory": directory,
                "force_full": force_full,
            },
        )
