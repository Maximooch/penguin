# Implementing a parser for the actions that the AI returns in its response.
# This is a simple parser that can be extended to support more complex actions. 
# The parser is based on the idea of "action types" and "parameters" that are returned in the AI response. 

# Inspired by the CodeAct paper: https://arxiv.org/abs/2402.01030
# CodeAct Github: https://github.com/xingyaoww/code-act

import logging
from typing import List
from enum import Enum
import re
import logging
from tools.tool_manager import ToolManager
from pathlib import Path
# from agent.task_utils import create_task, update_task, complete_task, list_tasks, create_project, add_subtask, get_task_details, get_project_details
from html import unescape
# from agent.task_manager import TaskManager
import asyncio
from utils.process_manager import ProcessManager

logger = logging.getLogger(__name__)

class ActionType(Enum):
    # READ = "read"
    # WRITE = "write"
    EXECUTE = "execute"
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

class CodeActAction:
    def __init__(self, action_type, params):
        self.action_type = action_type
        self.params = params

def parse_action(content: str) -> List[CodeActAction]:
    # Extract only the AI's response part
    ai_response = content.split("AI Response:\n", 1)[-1].split("\n\nAction Results:", 1)[0]
    
    pattern = r'<(\w+)>(.*?)</\1>'
    matches = re.finditer(pattern, ai_response, re.DOTALL)
    
    actions = []  # Initialize the actions list

    for match in matches:
        action_type = match.group(1).lower()
        params = unescape(match.group(2).strip())
        try:
            action_type_enum = ActionType[action_type.upper()]
            action = CodeActAction(action_type_enum, params)
            actions.append(action)
        except KeyError:
            # Ignore unrecognized action types
            pass
    
    return actions

class ActionExecutor:
    def __init__(self, tool_manager: ToolManager, task_manager=None):
        self.tool_manager = tool_manager
        # self.task_manager = task_manager
        self.process_manager = ProcessManager()
        self.current_process = None

    async def execute_action(self, action: CodeActAction) -> str:
        logger.debug(f"Attempting to execute action: {action.action_type.value}")
        action_map = {
            # ActionType.READ: lambda params: self.tool_manager.execute_tool("read_file", {"path": params}),
            # ActionType.WRITE: self._write_file,
            ActionType.EXECUTE: self._execute_code,
            ActionType.SEARCH: lambda params: self.tool_manager.execute_tool("grep_search", {"pattern": params}),
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
            
            logger.info(f"Action {action.action_type.value} executed successfully")
            return result
        except Exception as e:
            error_message = f"Error executing action {action.action_type.value}: {str(e)}"
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

    def _memory_search(self, params: str) -> str:
        query, k = params.split(':', 1) if ':' in params else (params, '5')
        return self.tool_manager.execute_tool("memory_search", {"query": query.strip(), "k": int(k.strip())})

    def _add_declarative_note(self, params: str) -> str:
        category, content = params.split(':', 1)
        return self.tool_manager.execute_tool("add_declarative_note", {"category": category.strip(), "content": content.strip()})

    # def _execute_subtask_add(self, params: str) -> str:
    #     parts = params.split(":", 2)
    #     if len(parts) < 3:
    #         return "Error: Invalid arguments for subtask_add. Expected format: ParentTaskName: SubtaskName: SubtaskDescription"
    #     parent_task_name = parts[0].strip()
    #     subtask_name = parts[1].strip()
    #     subtask_description = parts[2].strip()
        
    #     subtask = self.task_manager.add_subtask(parent_task_name, subtask_name, subtask_description)
    #     if subtask:
    #         self.task_manager.save_tasks()  # Add this line
    #         return f"Subtask created: {subtask}"
    #     else:
    #         return f"Parent task not found: {parent_task_name}"

    # def _execute_task_create(self, params: str) -> str:
    #     parts = params.split(":", 1)
    #     if len(parts) < 2:
    #         return "Error: Invalid arguments for task_create. Expected format: TaskName: TaskDescription"
    #     task_name = parts[0].strip()
    #     task_description = parts[1].strip()
    #     task = self.task_manager.create_task(task_name, task_description)
    #     if task:
    #         self.task_manager.save_tasks()  # Add this line
    #         return f"Task created: {task}"
    #     else:
    #         return f"Error creating task: {task_name}"

    # def _execute_task_update(self, params: str) -> str:
    #     parts = params.split(":", 1)
    #     if len(parts) < 2:
    #         return "Error: Invalid arguments for task_update. Expected format: TaskName: Progress"
    #     task_name = parts[0].strip()
    #     try:
    #         progress = int(parts[1].strip())
    #     except ValueError:
    #         return "Error: Progress must be an integer."
    #     result = self.task_manager.update_task_by_name(task_name, progress)
    #     self.task_manager.save_tasks()  # Add this line
    #     return result

    # def _execute_task_complete(self, params: str) -> str:
    #     task_name = params.strip()
    #     result = self.task_manager.complete_task(task_name)
    #     return result

    # def _execute_project_create(self, params: str) -> str:
    #     parts = params.split(":", 1)
    #     if len(parts) < 2:
    #         return "Error: Invalid arguments for project_create. Expected format: ProjectName: ProjectDescription"
    #     project_name = parts[0].strip()
    #     project_description = parts[1].strip()
    #     project = self.task_manager.create_project(project_name, project_description)
    #     if project:
    #         self.task_manager.save_tasks()  # Add this line
    #         return f"Project created: {project}"
    #     else:
    #         return f"Error creating project: {project_name}"

    # def _execute_project_complete(self, params: str) -> str:
    #     project_name = params.strip()
    #     result = self.task_manager.complete_project(project_name)
    #     self.task_manager.save_tasks()  # Add this line
    #     return result

    # def project_details(self, project_name: str) -> str:
    #     return self.task_manager.get_project_details(project_name)

    # def update_task_by_name(self, name: str, progress: int) -> str:
    #     task = self.get_task_by_name(name)
    #     if task:
    #         task.update_progress(progress)
    #         self.save_tasks()
    #         return f"Task updated: {task.name} to {progress}%"
    #     return f"Task not found: {name}"

    def _create_folder(self, params: str) -> str:
        return self.tool_manager.execute_tool("create_folder", {"path": params})

    def _add_summary_note(self, params: str) -> str:
        # If there's no explicit category, use a default one
        if ':' not in params:
            category = "general"
            content = params.strip()
        else:
            category, content = params.split(':', 1)
            category = category.strip()
            content = content.strip()
        
        return self.tool_manager.add_summary_note(category, content)
    
    def _perplexity_search(self, params: str) -> str:
        parts = params.split(':', 1)
        if len(parts) == 2:
            query, max_results = parts[0].strip(), int(parts[1].strip())
        else:
            query, max_results = params.strip(), 5

        results = self.tool_manager.execute_tool("perplexity_search", {"query": query, "max_results": max_results})
        
        # The results are already formatted as a string by the PerplexityProvider
        return results

    async def _process_start(self, params: str) -> str:
        logger.debug(f"Starting process with params: {params}")
        name, command = params.split(':', 1)
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
            return f"Entered process '{name}'. Initial output:\n{initial_output.decode()}"
        return f"Failed to enter process '{name}'"

    async def _process_send(self, params: str) -> str:
        if not self.current_process:
            return "Not currently in any process"
        return await self.process_manager.send_command(self.current_process, params.strip())

    async def _process_exit(self, params: str) -> str:
        if not self.current_process:
            return "Not currently in any process"
        result = await self.process_manager.exit_process(self.current_process)
        self.current_process = None
        return result

    def _workspace_search(self, params: str) -> str:
        parts = params.split(':', 1)
        if len(parts) == 2:
            query, max_results = parts[0].strip(), int(parts[1].strip())
        else:
            query, max_results = params.strip(), 5

        return self.tool_manager.execute_tool("workspace_search", {
            "query": query,
            "max_results": max_results
        })

    async def _memory_search(self, params: str) -> str:
        """
        Parse and execute memory search command
        Format: query:max_results:memory_type:categories:date_after:date_before
        Example: "project planning:5:logs:planning,projects:2024-01-01:2024-03-01"
        """
        try:
            parts = params.split(':')
            query = parts[0].strip()
            
            # Parse optional parameters
            max_results = int(parts[1]) if len(parts) > 1 and parts[1].strip() else 5
            memory_type = parts[2].strip() if len(parts) > 2 and parts[2].strip() else None
            categories = parts[3].strip().split(',') if len(parts) > 3 and parts[3].strip() else None
            date_after = parts[4].strip() if len(parts) > 4 and parts[4].strip() else None
            date_before = parts[5].strip() if len(parts) > 5 and parts[5].strip() else None

            results = self.tool_manager.search_memory(
                query=query,
                max_results=max_results,
                memory_type=memory_type,
                categories=categories,
                date_after=date_after,
                date_before=date_before
            )

            # Format results for display
            if not results:
                return "No results found."

            formatted_results = []
            for i, result in enumerate(results, 1):
                formatted_results.append(f"\n{i}. From: {result['metadata']['file_path']}")
                formatted_results.append(f"   Type: {result['metadata']['memory_type']}")
                formatted_results.append(f"   Categories: {result['metadata']['categories']}")
                formatted_results.append(f"   Relevance: {result['relevance']:.2f}/100")
                formatted_results.append(f"   Preview:")
                formatted_results.append(f"   {result['preview']}")
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