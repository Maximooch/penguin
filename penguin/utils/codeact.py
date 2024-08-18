from enum import Enum
import re
import logging

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
            action = CodeActAction(ActionType[action_type.upper()], params.strip())
            actions.append(action)
        except KeyError:
            # Handle unknown action types
            pass
    return actions
def execute_action(action, tool_manager):
    action_map = {
        ActionType.READ: tool_manager.read_file,
        ActionType.WRITE: lambda params: tool_manager.write_to_file(*params.split(':', 1)),
        ActionType.EXECUTE: tool_manager.execute_command,
        ActionType.SEARCH: tool_manager.grep_search,
        ActionType.CREATE_FILE: lambda params: tool_manager.create_file(*params.split(':', 1)),
        ActionType.CREATE_FOLDER: tool_manager.create_folder,
        ActionType.LIST_FILES: tool_manager.list_files,
        ActionType.LIST_FOLDERS: tool_manager.list_folders
    }
    
    try:
        return tool_manager.execute_tool(action.action_type.value, action.params)
    except Exception as e:
        logger.error(f"Error executing action {action.action_type}: {str(e)}")
        return f"Error: {str(e)}"