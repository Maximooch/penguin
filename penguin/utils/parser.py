# Implementing a parser for the actions that the AI returns in its response.
# This is a simple parser that can be extended to support more complex actions. 
# The parser is based on the idea of "action types" and "parameters" that are returned in the AI response. 

# Inspired by the CodeAct paper: https://arxiv.org/abs/2402.01030
# CodeAct Github: https://github.com/xingyaoww/code-act

from enum import Enum
import re
import logging
from tools.tool_manager import ToolManager

logger = logging.getLogger(__name__)

class ActionType(Enum):
    READ = "read"
    WRITE = "write"
    EXECUTE = "execute"
    SEARCH = "search"
    CREATE_FILE = "create_file"
    CREATE_FOLDER = "create_folder"
    LIST_FILES = "list_files"
    LIST_FOLDERS = "list_folders"
    GET_FILE_MAP = "get_file_map"
    # REPL, iPython, shell, bash, zsh, networking, file_management, task management, etc. 
    # TODO: Add more actions as needed

class CodeActAction:
    def __init__(self, action_type, params):
        self.action_type = action_type
        self.params = params

def parse_action(response):
    actions = []
    action_pattern = r'<(\w+)>(.*?)</\1>'
    matches = re.findall(action_pattern, response)
    for action_type, params in matches:
        try:
            action_type_upper = action_type.upper()
            if action_type_upper not in ActionType.__members__:
                logger.warning(f"Unknown action type: {action_type}")
                continue
            action = CodeActAction(ActionType[action_type_upper], params.strip())
            actions.append(action)
        except Exception as e:
            logger.error(f"Error parsing action: {str(e)}")
    return actions

class ActionExecutor:
    def __init__(self, tool_manager: ToolManager):
        self.tool_manager = tool_manager

    def execute_action(self, action: CodeActAction) -> str:
        action_map = {
            ActionType.READ: lambda params: self.tool_manager.execute_tool("read_file", {"path": params}),
            ActionType.WRITE: lambda params: self._write_file(params),
            ActionType.EXECUTE: lambda params: self._execute_code(params),
            ActionType.SEARCH: lambda params: self.tool_manager.execute_tool("grep_search", {"pattern": params}),
            ActionType.CREATE_FILE: lambda params: self._create_file(params),
            ActionType.CREATE_FOLDER: lambda params: self.tool_manager.execute_tool("create_folder", {"path": params}),
            ActionType.LIST_FILES: lambda params: self.tool_manager.execute_tool("list_files", {"path": params}),
            ActionType.LIST_FOLDERS: lambda params: self.tool_manager.execute_tool("list_files", {"path": params}),
            ActionType.GET_FILE_MAP: lambda params: self.tool_manager.execute_tool("get_file_map", {"directory": params}),
        }

        try:
            if action.action_type not in action_map:
                return f"Unknown action type: {action.action_type.value}"
            
            result = action_map[action.action_type](action.params)
            logger.info(f"Action {action.action_type.value} executed successfully")
            return f"Action {action.action_type.value} executed successfully: {result}"
        except Exception as e:
            error_message = f"Error executing action {action.action_type.value}: {str(e)}"
            logger.error(error_message)
            return error_message

    def _write_file(self, params: str) -> str:
        path, content = params.split(':', 1)
        return self.tool_manager.execute_tool("write_to_file", {"path": path.strip(), "content": content.strip()})

    def _create_file(self, params: str) -> str:
        path, content = params.split(':', 1)
        return self.tool_manager.execute_tool("create_file", {"path": path.strip(), "content": content.strip()})

    def _execute_code(self, params: str) -> str:
        if params.endswith('.py'):
            # It's a file, so we should read its contents first
            try:
                with open(params, 'r') as file:
                    code = file.read()
            except FileNotFoundError:
                return f"Error: File '{params}' not found."
        else:
            # It's a direct Python command
            code = params

        return self.tool_manager.execute_tool("code_execution", {"code": code})