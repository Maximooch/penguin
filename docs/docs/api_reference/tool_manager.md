# Tool Manager

The **ToolManager** acts as a central registry and execution hub for all tools available to Penguin. Tools are defined with a name, description, and JSON input schema. Expensive components such as the `NotebookExecutor` or browser automation tools are loaded lazily only when first used, keeping startup times fast.

## Responsibilities

- Registering and describing available tools
- Providing a single `execute_tool(name, params)` entry point
- Managing lazy initialization of optional subsystems (notebook, browser, etc.)
- Offering helper methods like `execute_code` or `perform_memory_search`

## Basic Usage

```python
from penguin.tools import ToolManager
from penguin.utils.log_error import log_error

config = {}
manager = ToolManager(config, log_error)

# Execute a grep search
result = manager.execute_tool("grep_search", {"pattern": "TODO"})
print(result)
```

The ToolManager is used throughout the core systems and by the `ActionExecutor` to run tools requested by the language model.

## Lazy Loading Design

`ToolManager` avoids importing heavy dependencies until they are actually needed. Properties such as `notebook_executor`, `perplexity_provider`, or the browser tools are initialized on first access. Each property checks an internal flag and constructs the component only once, keeping startup time and memory usage low.
