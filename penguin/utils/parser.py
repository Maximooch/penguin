# Implementing a parser for the actions that the AI returns in its response.
# This is a simple parser that can be extended to support more complex actions.
# The parser is based on the idea of "action types" and "parameters" that are returned in the AI response.

# Inspired by the CodeAct paper: https://arxiv.org/abs/2402.01030
# CodeAct Github: https://github.com/xingyaoww/code-act

import asyncio
import json
import logging
import re
from datetime import datetime
from enum import Enum
from html import unescape
from typing import List, Dict, Any, Optional, Callable, Awaitable
import base64
from penguin.local_task.manager import ProjectManager
from penguin.tools import ToolManager
from penguin.utils.process_manager import ProcessManager
from penguin.system.conversation import MessageCategory
from penguin.tools.browser_tools import BrowserScreenshotTool, browser_manager
from penguin.constants import (
    DELEGATE_EXPLORE_TASK_MAX_ITERATIONS_CAP,
    get_engine_max_iterations_default,
    DEFAULT_LARGE_FILE_THRESHOLD_BYTES,
)
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
    # Enhanced file operations
    LIST_FILES_FILTERED = "list_files_filtered"
    FIND_FILES_ENHANCED = "find_files_enhanced"
    ENHANCED_DIFF = "enhanced_diff"
    ANALYZE_PROJECT = "analyze_project"
    ENHANCED_READ = "enhanced_read"
    ENHANCED_WRITE = "enhanced_write"
    APPLY_DIFF = "apply_diff"
    MULTIEDIT = "multiedit"
    EDIT_WITH_PATTERN = "edit_with_pattern"
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
    # Response/Task completion signals (explicit termination)
    FINISH_RESPONSE = "finish_response"
    FINISH_TASK = "finish_task"
    # Legacy alias - kept for backward compatibility
    TASK_COMPLETED = "task_completed"  # Deprecated: use FINISH_TASK
    PROJECT_CREATE = "project_create"
    PROJECT_UPDATE = "project_update"
    PROJECT_DELETE = "project_delete"
    PROJECT_LIST = "project_list"
    PROJECT_DISPLAY = "project_display"
    DEPENDENCY_DISPLAY = "dependency_display"
    ANALYZE_CODEBASE = "analyze_codebase"
    REINDEX_WORKSPACE = "reindex_workspace"
    SEND_MESSAGE = "send_message"
    # Browser actions
    BROWSER_NAVIGATE = "browser_navigate"
    BROWSER_INTERACT = "browser_interact"
    BROWSER_SCREENSHOT = "browser_screenshot"
    # PyDoll browser actions
    PYDOLL_BROWSER_NAVIGATE = "pydoll_browser_navigate"
    PYDOLL_BROWSER_INTERACT = "pydoll_browser_interact"
    PYDOLL_BROWSER_SCREENSHOT = "pydoll_browser_screenshot"
    PYDOLL_BROWSER_SCROLL = "pydoll_browser_scroll"
    # PyDoll debug toggle
    PYDOLL_DEBUG_TOGGLE = "pydoll_debug_toggle"
    
    # Sub-agent tools (agents-as-tools)
    SPAWN_SUB_AGENT = "spawn_sub_agent"
    STOP_SUB_AGENT = "stop_sub_agent"
    RESUME_SUB_AGENT = "resume_sub_agent"
    DELEGATE = "delegate"
    DELEGATE_EXPLORE_TASK = "delegate_explore_task"
    
    # Repository management actions
    GET_REPOSITORY_STATUS = "get_repository_status"
    CREATE_AND_SWITCH_BRANCH = "create_and_switch_branch"
    COMMIT_AND_PUSH_CHANGES = "commit_and_push_changes"
    CREATE_IMPROVEMENT_PR = "create_improvement_pr"
    CREATE_FEATURE_PR = "create_feature_pr"
    CREATE_BUGFIX_PR = "create_bugfix_pr"


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


def strip_action_tags(content: str) -> str:
    """Strip action tags from content, returning clean text for conversation history.

    This removes all valid action tags (e.g., <execute_command>...</execute_command>,
    <finish_response>...</finish_response>) from the content, leaving only the
    narrative/conversational text.

    Args:
        content: The string content containing action tags

    Returns:
        Content with action tags removed and whitespace cleaned up
    """
    if not content:
        return content

    # Build pattern for all valid action types
    action_tag_pattern = "|".join([action_type.value for action_type in ActionType])
    # Match complete tag pairs: <action_type>...</action_type>
    pattern = f"<({action_tag_pattern})>.*?</\\1>"

    # Remove all action tags
    cleaned = re.sub(pattern, "", content, flags=re.DOTALL | re.IGNORECASE)

    # Clean up excessive whitespace left behind
    # Replace multiple newlines with at most two
    cleaned = re.sub(r'\n{3,}', '\n\n', cleaned)
    # Strip leading/trailing whitespace
    cleaned = cleaned.strip()

    return cleaned


def strip_incomplete_action_tags(content: str) -> str:
    """Strip incomplete/unclosed action tags from the end of content.

    When streaming is interrupted after detecting a complete action tag,
    there may be additional incomplete tags in the buffer (e.g., `<finish_response>`
    without its closing tag). This function removes such trailing fragments.

    Args:
        content: The string content that may have trailing incomplete tags

    Returns:
        Content with trailing incomplete tags removed
    """
    if not content:
        return content

    # Build pattern for valid action types
    action_tag_pattern = "|".join([action_type.value for action_type in ActionType])

    # Match incomplete opening tags at the end: <action_type> without </action_type>
    # This pattern finds <tag> or <tag>content... at the end without closing tag
    incomplete_pattern = f"<({action_tag_pattern})>(?:(?!</\\1>).)*$"

    # Remove trailing incomplete tags
    cleaned = re.sub(incomplete_pattern, "", content, flags=re.DOTALL | re.IGNORECASE)

    # Also remove partially-started opening tags at the end (e.g., <finish_ or <execute)
    # This handles cases where streaming was interrupted mid-tag
    partial_tag_pattern = f"<(?:{action_tag_pattern})?[^>]*$"
    cleaned = re.sub(partial_tag_pattern, "", cleaned, flags=re.IGNORECASE)

    # Also remove orphaned closing tags at the start (from previous incomplete)
    orphan_close_pattern = f"^\\s*</({action_tag_pattern})>"
    cleaned = re.sub(orphan_close_pattern, "", cleaned, flags=re.IGNORECASE)

    return cleaned.strip()


class ActionExecutor:
    def __init__(
        self,
        tool_manager: ToolManager,
        task_manager: ProjectManager,
        conversation_system=None,
        ui_event_callback: Optional[Callable[[str, Dict[str, Any]], Awaitable[None]]] = None,
    ):
        """Execute parsed actions and (optionally) emit UI events.
        
        Args:
            tool_manager: The ToolManager instance
            task_manager: The Project/Task manager
            conversation_system: Conversation manager (optional)
            ui_event_callback: Async callback to emit UI events (e.g. PenguinCore.emit_ui_event)
        """
        self.tool_manager = tool_manager
        self.task_manager = task_manager
        self.process_manager = ProcessManager()
        self.current_process = None
        self.conversation_system = conversation_system
        try:
            logger.info(
                "ActionExecutor initialized with ToolManager id=%s file_root=%s mode=%s",
                hex(id(tool_manager)) if tool_manager else None,
                getattr(tool_manager, '_file_root', None) if tool_manager else None,
                getattr(tool_manager, 'file_root_mode', None) if tool_manager else None,
            )
        except Exception:
            pass
        self._ui_event_cb = ui_event_callback
        # No direct initialization of expensive tools, we'll use tool_manager's properties

    async def execute_action(self, action: CodeActAction) -> str:
        """Execute an action and emit UI events if a callback is provided."""
        logger.debug(f"Attempting to execute action: {action.action_type.value}")
        try:
            logger.info(
                "ActionExecutor executing %s using ToolManager id=%s file_root=%s mode=%s",
                action.action_type.value,
                hex(id(self.tool_manager)) if self.tool_manager else None,
                getattr(self.tool_manager, '_file_root', None) if self.tool_manager else None,
                getattr(self.tool_manager, 'file_root_mode', None) if self.tool_manager else None,
            )
        except Exception:
            pass
        import uuid
        action_id = str(uuid.uuid4())[:8]
        
        # --------------------------------------------------
        # Emit *start* UI event
        # --------------------------------------------------
        if self._ui_event_cb:
            try:
                logger.debug(f"UI-emit start action id={action_id} type={action.action_type.value}")
                await self._ui_event_cb(
                    "action",
                    {
                        "id": action_id,
                        "type": action.action_type.value,
                        "params": action.params,
                    },
                )
            except Exception as e:
                logger.debug(f"UI event emit failed (action start): {e}")
        
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
            ActionType.MULTIEDIT: self._multiedit,
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
            # Response/Task completion signals
            ActionType.FINISH_RESPONSE: self._finish_response,
            ActionType.FINISH_TASK: self._finish_task,
            ActionType.TASK_COMPLETED: self._finish_task,  # Deprecated alias
            ActionType.DEPENDENCY_DISPLAY: self._dependency_display,
            ActionType.ANALYZE_CODEBASE: self._analyze_codebase,
            ActionType.REINDEX_WORKSPACE: self._reindex_workspace,
            ActionType.SEND_MESSAGE: self._send_message,
            # Browser actions
            ActionType.BROWSER_NAVIGATE: self._browser_navigate,
            ActionType.BROWSER_INTERACT: self._browser_interact,
            ActionType.BROWSER_SCREENSHOT: self._browser_screenshot,
            # PyDoll browser actions
            ActionType.PYDOLL_BROWSER_NAVIGATE: self._pydoll_browser_navigate,
            ActionType.PYDOLL_BROWSER_INTERACT: self._pydoll_browser_interact,
            ActionType.PYDOLL_BROWSER_SCREENSHOT: self._pydoll_browser_screenshot,
            ActionType.PYDOLL_BROWSER_SCROLL: self._pydoll_browser_scroll,
            # PyDoll debug toggle
            ActionType.PYDOLL_DEBUG_TOGGLE: self._pydoll_debug_toggle,
            # Sub-agent tools
            ActionType.SPAWN_SUB_AGENT: self._spawn_sub_agent,
            ActionType.STOP_SUB_AGENT: self._stop_sub_agent,
            ActionType.RESUME_SUB_AGENT: self._resume_sub_agent,
            ActionType.DELEGATE: self._delegate,
            ActionType.DELEGATE_EXPLORE_TASK: self._delegate_explore_task,
            # Enhanced file operations
            ActionType.LIST_FILES_FILTERED: self._list_files_filtered,
            ActionType.FIND_FILES_ENHANCED: self._find_files_enhanced,
            ActionType.ENHANCED_DIFF: self._enhanced_diff,
            ActionType.ANALYZE_PROJECT: self._analyze_project,
            ActionType.ENHANCED_READ: self._enhanced_read,
            ActionType.ENHANCED_WRITE: self._enhanced_write,
            ActionType.APPLY_DIFF: self._apply_diff,
            ActionType.EDIT_WITH_PATTERN: self._edit_with_pattern,
            # Repository management actions
            ActionType.GET_REPOSITORY_STATUS: self._get_repository_status,
            ActionType.CREATE_AND_SWITCH_BRANCH: self._create_and_switch_branch,
            ActionType.COMMIT_AND_PUSH_CHANGES: self._commit_and_push_changes,
            ActionType.CREATE_IMPROVEMENT_PR: self._create_improvement_pr,
            ActionType.CREATE_FEATURE_PR: self._create_feature_pr,
            ActionType.CREATE_BUGFIX_PR: self._create_bugfix_pr
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
                logger.debug(f"Executing sync handler for {action.action_type.value} in thread pool")
                # Offload synchronous tools to thread pool to avoid blocking the event loop
                loop = asyncio.get_running_loop()
                result = await loop.run_in_executor(None, handler, action.params)
                
                if asyncio.iscoroutine(result):
                    result = await result

            logger.info(f"Action {action.action_type.value} executed successfully")
            # --------------------------------------------------
            # Emit success UI event
            # --------------------------------------------------
            if self._ui_event_cb:
                try:
                    logger.debug(f"UI-emit success action_result id={action_id}")
                    await self._ui_event_cb(
                        "action_result",
                        {
                            "id": action_id,
                            "status": "completed",
                            "result": result if isinstance(result, str) else str(result),
                            "action": action.action_type.value,  # Standardized field name
                        },
                    )
                except Exception as e:
                    logger.debug(f"UI event emit failed (action result): {e}")
            return result
        except Exception as e:
            error_message = (
                f"Error executing action {action.action_type.value}: {str(e)}"
            )
            logger.error(error_message, exc_info=True)
            if self._ui_event_cb:
                try:
                    logger.debug(f"UI-emit error action_result id={action_id}")
                    await self._ui_event_cb(
                        "action_result",
                        {
                            "id": action_id,
                            "status": "error",
                            "result": error_message,
                            "action": action.action_type.value,  # Standardized field name
                        },
                    )
                except Exception as ee:
                    logger.debug(f"UI event emit failed (action error): {ee}")
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

    async def _send_message(self, params: str) -> str:
        try:
            payload = json.loads(params) if params.strip().startswith("{") else {"content": params}
        except json.JSONDecodeError as exc:
            raise ValueError(f"send_message expects JSON payload: {exc}")

        content = payload.get("content") or payload.get("message")
        if not content:
            raise ValueError("send_message requires 'content'")

        channel = payload.get("channel")
        message_type = payload.get("message_type", "message")
        metadata = payload.get("metadata") or {}
        sender = payload.get("sender")
        raw_targets = payload.get("targets") or payload.get("target") or payload.get("recipient")

        if raw_targets is None:
            targets = ["human"]
        elif isinstance(raw_targets, (list, tuple, set)):
            targets = list(raw_targets)
        else:
            targets = [str(raw_targets)]

        conversation = self.conversation_system
        core = getattr(conversation, "core", None)

        add_message_fn = None
        save_fn = None
        if callable(getattr(conversation, "add_message", None)):
            add_message_fn = conversation.add_message
            save_fn = getattr(conversation, "save", None)
        elif hasattr(conversation, "conversation") and callable(
            getattr(conversation.conversation, "add_message", None)
        ):
            add_message_fn = conversation.conversation.add_message
            save_fn = getattr(conversation, "save", None)

        if add_message_fn is None and core is None:
            raise RuntimeError("Penguin core unavailable for send_message action")

        results = []
        for target in targets:
            normalized = (target or "").strip()
            if normalized in ("", "human", "user"):
                delivered = False
                if core is not None:
                    try:
                        delivered = await core.send_to_human(
                            content,
                            message_type=message_type,
                            metadata=metadata,
                            channel=channel,
                        )
                    except Exception as exc:  # pragma: no cover - defensive logging
                        logger.warning("send_message core send_to_human failed: %s", exc)
                        delivered = False
                if not delivered and add_message_fn is not None:
                    add_message_fn(
                        role="assistant",
                        content=content,
                        category=MessageCategory.DIALOG,
                        metadata={
                            **metadata,
                            "via": "send_message_fallback",
                            "target": "human",
                            "channel": channel,
                            "message_type": message_type,
                            "sender": sender,
                        },
                        message_type=message_type,
                        agent_id=sender,
                        recipient_id="human",
                    )
                    if callable(save_fn):
                        try:
                            save_fn()
                        except Exception:  # pragma: no cover - best effort
                            logger.debug("send_message fallback save failed", exc_info=True)
                    results.append("human (logged)")
                else:
                    results.append("human")
            else:
                delivered = False
                if core is not None:
                    try:
                        delivered = await core.route_message(
                            normalized,
                            content,
                            message_type=message_type,
                            metadata=metadata,
                            agent_id=sender,
                            channel=channel,
                        )
                    except Exception as exc:  # pragma: no cover - defensive logging
                        logger.warning("send_message core route_message failed: %s", exc)
                        delivered = False
                if not delivered and add_message_fn is not None:
                    add_message_fn(
                        role="assistant",
                        content=content,
                        category=MessageCategory.DIALOG,
                        metadata={
                            **metadata,
                            "via": "send_message_fallback",
                            "target": normalized,
                            "channel": channel,
                            "message_type": message_type,
                            "sender": sender,
                        },
                        message_type=message_type,
                        agent_id=sender,
                        recipient_id=normalized,
                    )
                    if callable(save_fn):
                        try:
                            save_fn()
                        except Exception:  # pragma: no cover - best effort
                            logger.debug("send_message fallback save failed", exc_info=True)
                    results.append(f"{normalized} (logged)")
                elif delivered:
                    results.append(normalized)
                else:
                    results.append(f"{normalized} (failed)")

        return f"Sent message to {', '.join(results)}"

    # --------------------------------------------------
    # Sub-agent tools (agents-as-tools)
    # --------------------------------------------------

    async def _spawn_sub_agent(self, params: str) -> str:
        """Spawn a sub-agent; defaults to isolated session and context-window.

        JSON body:
          - id (required), parent (optional, default current), persona/system_prompt (optional)
          - share_session (bool, default False), share_context_window (bool, default False)
          - shared_context_window_max_tokens (int, optional), model_* overrides (optional), default_tools (optional)
          - initial_prompt (optional)
          - background (bool, default False): Run agent in background with initial_prompt
        """
        try:
            payload = json.loads(params) if params.strip() else {}
        except Exception as e:
            return f"Invalid JSON for spawn_sub_agent: {e}"

        agent_id = str(payload.get("id") or "").strip()
        if not agent_id:
            return "spawn_sub_agent requires 'id'"

        conversation = self.conversation_system
        core = getattr(conversation, "core", None)
        if core is None:
            return "Core unavailable for spawn_sub_agent"

        parent_id = str(payload.get("parent") or getattr(conversation, "current_agent_id", None) or "default").strip()
        share_session = bool(payload.get("share_session", False))
        share_cw = bool(payload.get("share_context_window", False))
        background = bool(payload.get("background", False))
        shared_context_window_max_tokens = payload.get("shared_context_window_max_tokens", payload.get("shared_cw_max_tokens"))  # Accept both keys
        try:
            shared_context_window_max_tokens = int(shared_context_window_max_tokens) if shared_context_window_max_tokens is not None else None
        except Exception:
            shared_context_window_max_tokens = None

        kwargs: Dict[str, Any] = {}
        for key in ("persona", "system_prompt", "model_config_id", "model_output_max_tokens", "default_tools"):
            if key in payload:
                kwargs[key] = payload[key]
        if isinstance(payload.get("model_overrides"), dict):
            kwargs["model_overrides"] = payload["model_overrides"]

        try:
            core.create_sub_agent(
                agent_id,
                parent_agent_id=parent_id,
                share_session=share_session,
                share_context_window=share_cw,
                shared_context_window_max_tokens=shared_context_window_max_tokens,
                **kwargs,
            )
        except Exception as e:
            return f"Failed to spawn sub-agent '{agent_id}': {e}"

        initial_prompt = payload.get("initial_prompt")
        if initial_prompt:
            if background:
                # Run agent in background using AgentExecutor
                try:
                    from penguin.multi.executor import get_executor, set_executor, AgentExecutor
                    executor = get_executor()
                    if executor is None:
                        executor = AgentExecutor(core)
                        set_executor(executor)

                    await executor.spawn_agent(
                        agent_id,
                        initial_prompt,
                        metadata={
                            "parent": parent_id,
                            "share_session": share_session,
                            "share_context_window": share_cw,
                        }
                    )
                    return f"Spawned sub-agent '{agent_id}' running in background (parent='{parent_id}')"
                except Exception as e:
                    return f"Failed to spawn background agent '{agent_id}': {e}"
            else:
                # Synchronous: send message and wait
                try:
                    await core.send_to_agent(agent_id, initial_prompt)
                except Exception as e:
                    logger.warning(f"Failed to send initial_prompt to {agent_id}: {e}")

        return f"Spawned sub-agent '{agent_id}' (parent='{parent_id}', share_session={share_session}, share_context_window={share_cw})"


    async def _delegate_explore_task(self, params: str) -> str:
        """Delegate an autonomous exploration task to haiku (later general sub agent) with tool access.

        The sub-agent can list directories, read files, and search.
        It runs a mini action loop until it has enough info to respond.

        JSON body:
          - task (required): What to explore/analyze
          - directory (optional): Starting directory (default: current)
          - max_iterations (optional): Max tool rounds (default: 10)

        Example: <delegate_explore_task>{"task": "Explore this codebase and summarize the architecture"}</delegate_explore_task>
        """
        import logging
        import os
        import re
        from pathlib import Path

        _logger = logging.getLogger(__name__)

        try:
            payload = json.loads(params) if params.strip() else {}
        except Exception as e:
            return f"Invalid JSON: {e}"

        task = payload.get("task", "").strip()
        if not task:
            return "delegate_explore_task requires 'task'"

        start_dir = payload.get("directory", ".")
        requested_max_iterations = payload.get("max_iterations", None)
        if requested_max_iterations is None:
            requested_max_iterations = get_engine_max_iterations_default()
        try:
            requested_max_iterations = int(requested_max_iterations)
        except Exception:
            requested_max_iterations = get_engine_max_iterations_default()

        max_iterations = min(
            requested_max_iterations,
            int(DELEGATE_EXPLORE_TASK_MAX_ITERATIONS_CAP),
        )

        # Get current working directory for context
        cwd = os.getcwd()

        # Tool execution functions
        def execute_list_files(path: str) -> str:
            try:
                p = Path(path)
                if not p.exists():
                    return f"Directory not found: {path}"
                if not p.is_dir():
                    return f"Not a directory: {path}"

                items = []
                for item in sorted(p.iterdir())[:50]:  # Limit to 50 items
                    if item.name.startswith('.'):
                        continue  # Skip hidden
                    prefix = "📁 " if item.is_dir() else "📄 "
                    size = f" ({item.stat().st_size} bytes)" if item.is_file() else ""
                    items.append(f"{prefix}{item.name}{size}")

                return f"Contents of {path}:\n" + "\n".join(items) if items else f"{path} is empty"
            except Exception as e:
                return f"Error listing {path}: {e}"

        def execute_read_file(path: str, max_lines: int = 200) -> str:
            try:
                p = Path(path)
                if not p.exists():
                    return f"File not found: {path}"
                if not p.is_file():
                    return f"Not a file: {path}"
                if p.stat().st_size > DEFAULT_LARGE_FILE_THRESHOLD_BYTES:
                    return f"File too large: {path} ({p.stat().st_size} bytes)"

                content = p.read_text(errors='replace')
                lines = content.splitlines()[:max_lines]
                if len(content.splitlines()) > max_lines:
                    lines.append(f"... (truncated, {len(content.splitlines())} total lines)")

                return f"=== {path} ===\n" + "\n".join(lines)
            except Exception as e:
                return f"Error reading {path}: {e}"

        def execute_search(pattern: str, path: str = ".") -> str:
            try:
                import subprocess
                result = subprocess.run(
                    ["grep", "-rn", "--include=*.py", "--include=*.js", "--include=*.ts", 
                     "--include=*.md", "--include=*.json", "--include=*.yaml", "--include=*.yml",
                     pattern, path],
                    capture_output=True, text=True, timeout=10
                )
                matches = result.stdout.strip().splitlines()[:20]  # Limit results
                if matches:
                    return f"Search results for '{pattern}':\n" + "\n".join(matches)
                return f"No matches found for '{pattern}'"
            except Exception as e:
                return f"Search error: {e}"

        def execute_tool(name: str, args: dict) -> str:
            if name == "list_files":
                return execute_list_files(args.get("path", "."))
            elif name == "read_file":
                return execute_read_file(args.get("path", ""), args.get("max_lines", 200))
            elif name == "search":
                return execute_search(args.get("pattern", ""), args.get("path", "."))
            return f"Unknown tool: {name}"

        # System prompt for the explorer
        system_prompt = f"""You are a codebase exploration assistant. Your job is to explore and understand codebases.

You have these tools:
- list_files: List directory contents
- read_file: Read a file (max 200 lines)
- search: Search for patterns in files

Current directory: {cwd}
Starting directory: {start_dir}

IMPORTANT:
1. Start by listing the root directory to understand the structure
2. Read key files like README.md, package.json, pyproject.toml, etc.
3. Identify the main technology stack and architecture
4. Be systematic but efficient - don't read every file
5. When you have enough information, provide a clear summary

To use a tool, respond with a JSON block:
```json
{{"tool": "tool_name", "args": {{"param": "value"}}}}
```

When done exploring, provide your final summary WITHOUT any tool calls."""

        try:
            from penguin.llm.openrouter_gateway import OpenRouterGateway
            from penguin.llm.model_config import ModelConfig

            model_config = ModelConfig(
                model="anthropic/claude-haiku-4.5",
                provider="openrouter",
                max_output_tokens=2000,
            )
            gateway = OpenRouterGateway(model_config)

            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": task},
            ]

            final_content = ""

            # Mini action loop
            for iteration in range(max_iterations):
                _logger.info(f"[DELEGATE] Iteration {iteration + 1}/{max_iterations}")

                response = await gateway.get_response(messages=messages)

                # Extract content from response
                content = ""
                if isinstance(response, dict):
                    content = response.get("content", "")
                    if not content and "choices" in response:
                        choices = response.get("choices", [])
                        if choices:
                            content = choices[0].get("message", {}).get("content", "")
                elif hasattr(response, "content"):
                    content = response.content
                else:
                    content = str(response)

                final_content = content

                # Check for tool calls (look for JSON blocks)
                tool_match = re.search(r'```json\s*({[^`]+})\s*```', content, re.DOTALL)
                if not tool_match:
                    # Also try without code fence
                    tool_match = re.search(r'\{"tool":\s*"(\w+)"', content)

                if tool_match:
                    try:
                        # Parse tool call
                        if '```' in content:
                            tool_json = json.loads(tool_match.group(1))
                        else:
                            # Extract full JSON object
                            start = content.find('{"tool"')
                            depth = 0
                            end = start
                            for i, c in enumerate(content[start:]):
                                if c == '{': depth += 1
                                elif c == '}': depth -= 1
                                if depth == 0:
                                    end = start + i + 1
                                    break
                            tool_json = json.loads(content[start:end])

                        tool_name = tool_json.get("tool")
                        tool_args = tool_json.get("args", {})

                        _logger.info(f"[DELEGATE] Tool call: {tool_name}({tool_args})")

                        # Execute tool
                        result = execute_tool(tool_name, tool_args)

                        # Add to conversation
                        messages.append({"role": "assistant", "content": content})
                        messages.append({"role": "user", "content": f"Tool result:\n{result}"})

                    except json.JSONDecodeError as e:
                        _logger.warning(f"[DELEGATE] Failed to parse tool call: {e}")
                        # Treat as final response
                        return f"[Haiku Explorer]:\n{content}"
                else:
                    # No tool call - this is the final response
                    return f"[Haiku Explorer]:\n{content}"

            # Max iterations reached
            return f"[Haiku Explorer] (max iterations reached):\n{final_content}"

        except Exception as e:
            _logger.error(f"delegate_explore_task failed: {e}", exc_info=True)
            return f"delegate_explore_task failed: {e}"


    async def _stop_sub_agent(self, params: str) -> str:
        """Stop/pause a sub-agent. Also cancels background tasks if running."""
        try:
            payload = json.loads(params) if params.strip() else {}
        except Exception as e:
            return f"Invalid JSON for stop_sub_agent: {e}"
        agent_id = str(payload.get("id") or "").strip()
        if not agent_id:
            return "stop_sub_agent requires 'id'"
        conversation = self.conversation_system
        core = getattr(conversation, "core", None)
        if core is None:
            return "Core unavailable for stop_sub_agent"

        cancelled_background = False
        try:
            # Try to cancel background task if running in executor
            from penguin.multi.executor import get_executor
            executor = get_executor()
            if executor:
                status = executor.get_status(agent_id)
                if status and status.get("state") in ("pending", "running"):
                    cancelled_background = await executor.cancel(agent_id)
        except Exception as e:
            logger.debug(f"Failed to cancel background task for '{agent_id}': {e}")

        try:
            # Also pause in conversation manager
            if hasattr(core, "set_agent_paused"):
                core.set_agent_paused(agent_id, True)

            if cancelled_background:
                return f"Stopped sub-agent '{agent_id}' (background task cancelled)"
            return f"Paused sub-agent '{agent_id}'"
        except Exception as e:
            return f"Failed to pause sub-agent '{agent_id}': {e}"

    async def _resume_sub_agent(self, params: str) -> str:
        try:
            payload = json.loads(params) if params.strip() else {}
        except Exception as e:
            return f"Invalid JSON for resume_sub_agent: {e}"
        agent_id = str(payload.get("id") or "").strip()
        if not agent_id:
            return "resume_sub_agent requires 'id'"
        conversation = self.conversation_system
        core = getattr(conversation, "core", None)
        if core is None:
            return "Core unavailable for resume_sub_agent"
        try:
            if hasattr(core, "set_agent_paused"):
                core.set_agent_paused(agent_id, False)
            return f"Resumed sub-agent '{agent_id}'"
        except Exception as e:
            return f"Failed to resume sub-agent '{agent_id}': {e}"

    async def _delegate(self, params: str) -> str:
        """Delegate a task to a sub-agent.

        JSON body:
          - child (required): Target sub-agent ID
          - content (required): Task content
          - parent (optional): Parent agent ID
          - channel (optional): Logical channel
          - metadata (optional): Additional metadata
          - background (bool, default False): Run in background
          - wait (bool, default False): Wait for result when background=true
          - timeout (float, optional): Timeout in seconds when wait=true
        """
        try:
            payload = json.loads(params) if params.strip() else {}
        except Exception as e:
            return f"Invalid JSON for delegate: {e}"

        child = str(payload.get("child") or "").strip()
        content = payload.get("content")
        if not child or content is None:
            return "delegate requires 'child' and 'content'"

        conversation = self.conversation_system
        core = getattr(conversation, "core", None)
        if core is None:
            return "Core unavailable for delegate"

        parent = str(payload.get("parent") or getattr(conversation, "current_agent_id", None) or "default").strip()
        channel = payload.get("channel")
        metadata = payload.get("metadata") or {}
        background = bool(payload.get("background", False))
        wait = bool(payload.get("wait", False))
        timeout = payload.get("timeout")

        # Record delegation event in both parent and child logs (best-effort)
        try:
            cm = getattr(core, "conversation_manager", None)
            if cm and hasattr(cm, "log_delegation_event"):
                import uuid as _uuid
                delegation_id = _uuid.uuid4().hex[:8]
                cm.log_delegation_event(
                    delegation_id=delegation_id,
                    parent_agent_id=parent,
                    child_agent_id=child,
                    event="request_sent",
                    message=str(content)[:140],
                    metadata={**metadata, **({"channel": channel} if channel else {})},
                )
                metadata = {**metadata, "delegation_id": delegation_id}
        except Exception as e:
            logger.debug(f"Failed to add delegation_id to metadata: {e}")

        if background:
            # Run delegated task in background using AgentExecutor
            try:
                from penguin.multi.executor import get_executor, set_executor, AgentExecutor
                import asyncio

                executor = get_executor()
                if executor is None:
                    executor = AgentExecutor(core)
                    set_executor(executor)

                # Check if agent is already running
                status = executor.get_status(child)
                if status and status.get("state") in ("pending", "running"):
                    return f"Agent '{child}' is already running a background task"

                await executor.spawn_agent(
                    child,
                    str(content),
                    metadata={
                        "parent": parent,
                        "channel": channel,
                        **(metadata or {}),
                    }
                )

                if wait:
                    try:
                        result = await executor.wait_for(child, timeout=timeout)
                        return f"Delegated to '{child}' (background, waited): {result}"
                    except asyncio.TimeoutError:
                        return f"Delegated to '{child}' (background, timed out after {timeout}s)"
                else:
                    return f"Delegated to '{child}' running in background"
            except Exception as e:
                return f"Failed to delegate background task to '{child}': {e}"
        else:
            # Synchronous delegation via message passing
            try:
                await core.send_to_agent(
                    child,
                    content,
                    message_type="message",
                    metadata=metadata,
                    channel=channel,
                )
                return f"Delegated to '{child}' from '{parent}'"
            except Exception as e:
                return f"Failed to delegate to '{child}': {e}"

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

    def _finish_response(self, params: str) -> str:
        """Signal that the conversational response is complete.
        
        Called by the LLM when it has finished responding and has no more
        actions to take. This stops the run_response loop.
        
        Format: optional summary
        """
        try:
            return self.tool_manager.task_tools.finish_response(params.strip() if params else None)
        except Exception as e:
            return f"Error signaling response completion: {str(e)}"

    def _finish_task(self, params: str) -> str:
        """Signal that the LLM believes the task objective is achieved.
        
        This transitions the task to PENDING_REVIEW status for human approval.
        The summary becomes the review note.
        
        Format: summary (optional) or JSON {"summary": "...", "status": "done|partial|blocked"}
        """
        try:
            return self.tool_manager.task_tools.finish_task(params.strip() if params else None)
        except Exception as e:
            return f"Error signaling task completion: {str(e)}"

    # Deprecated: kept for backward compatibility
    def _task_completed(self, params: str) -> str:
        """Deprecated: Use _finish_task instead."""
        return self._finish_task(params)

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
                
                # Determine target 'add_message' method
                add_message_fn = None
                if callable(getattr(self.conversation_system, 'add_message', None)):
                    add_message_fn = self.conversation_system.add_message
                elif hasattr(self.conversation_system, 'conversation') and callable(getattr(self.conversation_system.conversation, 'add_message', None)):
                    add_message_fn = self.conversation_system.conversation.add_message
                
                # Create multimodal content
                multimodal_content = [
                    {"type": "text", "text": description},
                    {"type": "image_url", "image_path": result["filepath"]}
                ]
                
                if add_message_fn:
                    logger.info(f"Adding PyDoll screenshot to conversation via {add_message_fn}: {multimodal_content}")
                    add_message_fn(
                        role="user",
                        content=multimodal_content,
                        category=MessageCategory.DIALOG
                    )
                    return f"PyDoll screenshot saved to {result['filepath']} and added to conversation"
                else:
                    logger.warning("No suitable add_message method found; conversation update skipped")
                    return f"PyDoll screenshot saved to {result['filepath']} (conversation update skipped)"
            else:
                error_msg = result.get("error", "Failed to capture PyDoll screenshot or file not found")
                logger.error(f"PyDoll screenshot error: {error_msg}")
                return error_msg
        except Exception as e:
            error_message = f"Error taking PyDoll screenshot: {str(e)}"
            logger.error(error_message, exc_info=True)
            return error_message

    async def _pydoll_browser_scroll(self, params: str) -> str:
        """Scroll the page or an element using PyDoll.
        Formats:
          - to:top|bottom
          - page:down|up|end|home[:repeat]
          - by:deltaY[:deltaX][:repeat]
          - element:selector[:selector_type][:behavior]
        Defaults: selector_type=css, behavior=auto, repeat=1
        """
        try:
            from penguin.tools.pydoll_tools import PyDollBrowserScrollTool

            parts = params.split(":") if params else []
            if not parts:
                return "Invalid scroll params"
            mode = parts[0].strip().lower()

            tool = PyDollBrowserScrollTool()

            if mode == "to" and len(parts) >= 2:
                to = parts[1].strip().lower()
                return await tool.execute(mode="to", to=to)

            if mode == "page":
                direction = parts[1].strip().lower() if len(parts) >= 2 else "down"
                repeat = int(parts[2]) if len(parts) >= 3 and parts[2].strip().isdigit() else 1
                return await tool.execute(mode="page", to=direction, repeat=repeat)

            if mode == "by":
                dy = int(parts[1]) if len(parts) >= 2 and parts[1].strip().lstrip("-+").isdigit() else 800
                dx = int(parts[2]) if len(parts) >= 3 and parts[2].strip().lstrip("-+").isdigit() else 0
                repeat = int(parts[3]) if len(parts) >= 4 and parts[3].strip().isdigit() else 1
                return await tool.execute(mode="by", delta_y=dy, delta_x=dx, repeat=repeat)

            if mode == "element" and len(parts) >= 2:
                selector = parts[1]
                selector_type = parts[2].strip().lower() if len(parts) >= 3 and parts[2].strip() else "css"
                behavior = parts[3].strip().lower() if len(parts) >= 4 and parts[3].strip() else "auto"
                return await tool.execute(mode="element", selector=selector, selector_type=selector_type, behavior=behavior)

            return "Invalid scroll command"
        except Exception as e:
            error_message = f"Error scrolling with PyDoll browser: {str(e)}"
            logger.error(error_message)
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

    def _list_files_filtered(self, params: str) -> str:
        """Enhanced file listing. Format: path:group_by_type:show_hidden"""
        parts = params.split(":")
        path = parts[0].strip() if parts and parts[0].strip() else "."
        group_by_type = parts[1].strip().lower() == "true" if len(parts) > 1 else False
        show_hidden = parts[2].strip().lower() == "true" if len(parts) > 2 else False
        
        return self.tool_manager.execute_tool("list_files", {
            "path": path,
            "group_by_type": group_by_type,
            "show_hidden": show_hidden
        })

    def _find_files_enhanced(self, params: str) -> str:
        """Enhanced file finding. Format: pattern:search_path:include_hidden:file_type"""
        parts = params.split(":")
        if not parts or not parts[0].strip():
            return "Error: Pattern is required"
        
        pattern = parts[0].strip()
        search_path = parts[1].strip() if len(parts) > 1 and parts[1].strip() else "."
        include_hidden = parts[2].strip().lower() == "true" if len(parts) > 2 else False
        file_type = parts[3].strip() if len(parts) > 3 and parts[3].strip() else None
        
        return self.tool_manager.execute_tool("find_file", {
            "filename": pattern,
            "search_path": search_path,
            "include_hidden": include_hidden,
            "file_type": file_type
        })

    def _enhanced_diff(self, params: str) -> str:
        """Compare two files with enhanced diff. Format: file1:file2:semantic"""
        parts = params.split(":")
        if len(parts) < 2:
            return "Error: Need at least two files to compare"
        
        file1 = parts[0].strip()
        file2 = parts[1].strip()
        semantic = parts[2].strip().lower() == "true" if len(parts) > 2 else True
        
        return self.tool_manager.execute_tool("enhanced_diff", {
            "file1": file1,
            "file2": file2,
            "semantic": semantic
        })

    def _analyze_project(self, params: str) -> str:
        """Analyze project structure. Format: directory:include_external"""
        parts = params.split(":")
        directory = parts[0].strip() if parts and parts[0].strip() else "."
        include_external = parts[1].strip().lower() == "true" if len(parts) > 1 else False
        
        return self.tool_manager.execute_tool("analyze_project", {
            "directory": directory,
            "include_external": include_external
        })

    def _enhanced_read(self, params: str) -> str:
        """Enhanced file reading. Format: path:show_line_numbers:max_lines"""
        parts = params.split(":")
        if not parts or not parts[0].strip():
            return "Error: File path is required"
        
        path = parts[0].strip()
        show_line_numbers = parts[1].strip().lower() == "true" if len(parts) > 1 else False
        max_lines = int(parts[2].strip()) if len(parts) > 2 and parts[2].strip().isdigit() else None
        
        return self.tool_manager.execute_tool("read_file", {
            "path": path,
            "show_line_numbers": show_line_numbers,
            "max_lines": max_lines
        })

    def _enhanced_write(self, params: str) -> str:
        """Enhanced file writing. Format: path:content:backup
        
        Parsing strategy: Find path from start (first colon), then check if
        the content ends with :true or :false for the backup flag. This handles
        content that contains colons (e.g., CSS, URLs).
        """
        first_sep = params.find(":")
        if first_sep == -1:
            return "Error: Need path and content (format: path:content[:backup])"
        
        path = params[:first_sep].strip()
        remainder = params[first_sep + 1:]
        
        if not path or not remainder:
            return "Error: Need path and content"
        
        # Default backup to True
        backup = True
        content = remainder
        
        # Check if remainder ends with :true or :false (backup flag)
        # Only consider it a flag if it's at the very end with no newlines
        if ":" in remainder:
            content_part, flag = remainder.rsplit(":", 1)
            flag_stripped = flag.strip().lower()
            # Only treat as backup flag if it's exactly "true" or "false"
            # and doesn't contain newlines (to avoid matching content that ends with :something)
            if flag_stripped in {"true", "false"} and "\n" not in flag and "\r" not in flag:
                backup = flag_stripped == "true"
                content = content_part
        
        return self.tool_manager.execute_tool("write_to_file", {
            "path": path,
            "content": content,
            "backup": backup
        })

    def _apply_diff(self, params: str) -> str:
        """Apply a diff to edit a file. Format: file_path:diff_content:backup"""
        first_sep = params.find(":")
        if first_sep == -1:
            return "Error: Need file path and diff content"

        file_path = params[:first_sep].strip()
        remainder = params[first_sep + 1 :]
        if not file_path or not remainder:
            return "Error: Need file path and diff content"

        backup = True
        diff_content = remainder

        # Optional backup flag can be appended as :true or :false with no newline.
        if ":" in remainder:
            diff_part, flag = remainder.rsplit(":", 1)
            flag_stripped = flag.strip().lower()
            if flag_stripped in {"true", "false"} and "\n" not in flag and "\r" not in flag:
                backup = flag_stripped == "true"
                diff_content = diff_part

        return self.tool_manager.execute_tool("apply_diff", {
            "file_path": file_path,
            "diff_content": diff_content,
            "backup": backup
        })

    def _multiedit(self, params: str) -> str:
        """Apply multi-file edits atomically. Content is the multiedit block or unified patch. Default dry-run."""
        content = params
        # Optional header directive: apply=true on the first line
        do_apply = False
        m = re.match(r"^apply\s*[:=]\s*(true|false)\s*\n", content, flags=re.IGNORECASE)
        if m:
            do_apply = m.group(1).lower() == 'true'
            content = content[m.end():]
        return self.tool_manager.execute_tool("multiedit_apply", {
            "content": content,
            "apply": do_apply,
        })

    def _edit_with_pattern(self, params: str) -> str:
        """Edit file with pattern replacement. Format: file_path:search_pattern:replacement:backup
        
        Note: Uses reverse split to handle colons in replacement text.
        """
        # Split from the right to handle optional backup flag first
        parts = params.rsplit(":", 1)
        backup = False
        content_parts = parts[0]
        
        # Check if last part is the backup flag (true/false)
        if len(parts) == 2 and parts[1].strip().lower() in ("true", "false"):
            backup = parts[1].strip().lower() == "true"
        else:
            # No backup flag, treat entire string as content
            content_parts = params
            backup = True  # Default to backup
        
        # Now split the content part into file_path:search_pattern:replacement
        # Split only on first 2 colons to preserve colons in replacement text
        parts = content_parts.split(":", 2)
        if len(parts) < 3:
            return "Error: Need file_path:search_pattern:replacement format"
        
        file_path = parts[0].strip()
        search_pattern = parts[1]  # Don't strip - regex patterns may need whitespace
        replacement = parts[2]      # Don't strip - replacement may need whitespace (and may contain colons!)
        
        return self.tool_manager.execute_tool("edit_with_pattern", {
            "file_path": file_path,
            "search_pattern": search_pattern,
            "replacement": replacement,
            "backup": backup
        })
    
    # Repository management action handlers
    def _get_repository_status(self, params: str) -> str:
        """Get status of a repository. Format: repo_owner:repo_name"""
        parts = params.split(":", 1)
        if len(parts) < 2:
            return "Error: Need repo_owner:repo_name format"
        
        repo_owner = parts[0].strip()
        repo_name = parts[1].strip()
        
        return self.tool_manager.execute_tool("get_repository_status", {
            "repo_owner": repo_owner,
            "repo_name": repo_name
        })
    
    def _create_and_switch_branch(self, params: str) -> str:
        """Create and switch to a new git branch. Format: repo_owner:repo_name:branch_name"""
        parts = params.split(":", 2)
        if len(parts) < 3:
            return "Error: Need repo_owner:repo_name:branch_name format"
        
        repo_owner = parts[0].strip()
        repo_name = parts[1].strip()
        branch_name = parts[2].strip()
        
        return self.tool_manager.execute_tool("create_and_switch_branch", {
            "repo_owner": repo_owner,
            "repo_name": repo_name,
            "branch_name": branch_name
        })
    
    def _commit_and_push_changes(self, params: str) -> str:
        """Commit and push changes. Format: repo_owner:repo_name:commit_message"""
        parts = params.split(":", 2)
        if len(parts) < 3:
            return "Error: Need repo_owner:repo_name:commit_message format"
        
        repo_owner = parts[0].strip()
        repo_name = parts[1].strip()
        commit_message = parts[2].strip()
        
        return self.tool_manager.execute_tool("commit_and_push_changes", {
            "repo_owner": repo_owner,
            "repo_name": repo_name,
            "commit_message": commit_message
        })
    
    def _create_improvement_pr(self, params: str) -> str:
        """Create improvement PR. Format: repo_owner:repo_name:title:description:files_changed"""
        parts = params.split(":", 4)
        if len(parts) < 4:
            return "Error: Need repo_owner:repo_name:title:description format (files_changed is optional)"
        
        repo_owner = parts[0].strip()
        repo_name = parts[1].strip()
        title = parts[2].strip()
        description = parts[3].strip()
        files_changed = parts[4].strip() if len(parts) > 4 else None
        
        return self.tool_manager.execute_tool("create_improvement_pr", {
            "repo_owner": repo_owner,
            "repo_name": repo_name,
            "title": title,
            "description": description,
            "files_changed": files_changed
        })
    
    def _create_feature_pr(self, params: str) -> str:
        """Create feature PR. Format: repo_owner:repo_name:feature_name:description:implementation_notes:files_modified"""
        parts = params.split(":", 5)
        if len(parts) < 4:
            return "Error: Need repo_owner:repo_name:feature_name:description format"
        
        repo_owner = parts[0].strip()
        repo_name = parts[1].strip()
        feature_name = parts[2].strip()
        description = parts[3].strip()
        implementation_notes = parts[4].strip() if len(parts) > 4 else ""
        files_modified = parts[5].strip() if len(parts) > 5 else None
        
        return self.tool_manager.execute_tool("create_feature_pr", {
            "repo_owner": repo_owner,
            "repo_name": repo_name,
            "feature_name": feature_name,
            "description": description,
            "implementation_notes": implementation_notes,
            "files_modified": files_modified
        })
    
    def _create_bugfix_pr(self, params: str) -> str:
        """Create bug fix PR. Format: repo_owner:repo_name:bug_description:fix_description:files_fixed"""
        parts = params.split(":", 4)
        if len(parts) < 4:
            return "Error: Need repo_owner:repo_name:bug_description:fix_description format"
        
        repo_owner = parts[0].strip()
        repo_name = parts[1].strip()
        bug_description = parts[2].strip()
        fix_description = parts[3].strip()
        files_fixed = parts[4].strip() if len(parts) > 4 else None
        
        return self.tool_manager.execute_tool("create_bugfix_pr", {
            "repo_owner": repo_owner,
            "repo_name": repo_name,
            "bug_description": bug_description,
            "fix_description": fix_description,
            "files_fixed": files_fixed
        })
