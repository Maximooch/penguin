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
