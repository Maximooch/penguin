# Parser System

Penguin interprets special XML-like tags from the model's responses to determine actions. The `parse_action` function scans the text and returns a list of `CodeActAction` objects. Each action has a type (from the `ActionType` enum) and a parameter string.

## Action Execution

Parsed actions are handed to the `ActionExecutor`. This component routes each action to the appropriate ToolManager method or helper routine. Many actions correspond directly to tool names while others manage processes or projects.

```python
from penguin.utils.parser import parse_action, ActionExecutor
from penguin.tools import ToolManager

text = "<grep_search>TODO</grep_search>"
actions = parse_action(text)
executor = ActionExecutor(ToolManager({}, lambda e: print(e)), None)
result = await executor.execute_action(actions[0])
```

The parser system allows the language model to trigger complex behaviors in a controlled manner.

## Supported Action Tags

The following tags can appear in model responses:

`execute`, `execute_command`, `search`, `memory_search`, `add_declarative_note`, `add_summary_note`, `perplexity_search`, `process_start`, `process_stop`, `process_status`, `process_list`, `process_enter`, `process_send`, `process_exit`, `workspace_search`, `task_create`, `task_update`, `task_complete`, `task_delete`, `task_list`, `task_display`, `project_create`, `project_update`, `project_delete`, `project_list`, `project_display`, `dependency_display`, `analyze_codebase`, `reindex_workspace`, `browser_navigate`, `browser_interact`, `browser_screenshot`, `pydoll_browser_navigate`, `pydoll_browser_interact`, `pydoll_browser_screenshot`, and `pydoll_debug_toggle`.

## Custom Actions

To add your own action, extend `ActionType` with a new value and implement handling in `ActionExecutor`. For example:

```python
class ActionType(Enum):
    MY_CUSTOM_ACTION = "my_custom_action"

class ActionExecutor:
    async def execute_action(self, action: CodeActAction) -> str:
        if action.action_type == ActionType.MY_CUSTOM_ACTION:
            return do_something(action.params)
        ...
```
