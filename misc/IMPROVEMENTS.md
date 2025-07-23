
# Penguin Tool System Improvement Plan

This document outlines a plan to refactor and improve the tool system in Penguin. The goal is to make the system more robust, scalable, and easier to maintain, bringing it in line with modern agent architectures.

## 1. Structured Tool Calls with JSON

The current system parses arguments from a single string, which is brittle. We will move to a structured format (JSON) for tool calls.

**Current:**
```xml
<execute_command>ls -l</execute_command>
```

**Proposed:**
```xml
<execute_command>
{
  "command": "ls -l"
}
</execute_command>
```

This will require updating the `parse_action` function in `parser.py` to parse JSON and updating the model's prompts to generate JSON.

## 2. Tool Definition as Classes

Instead of defining tool schemas in a large dictionary, each tool will be a class. This makes the system more modular and scalable.

We will create a base `Tool` class:

```python
from abc import ABC, abstractmethod
import pydantic

class BaseTool(ABC):
    name: str
    description: str
    args_schema: pydantic.BaseModel

    @abstractmethod
    def execute(self, args: pydantic.BaseModel):
        pass
```

Each tool will inherit from this base class:

```python
class ReadFileArgs(pydantic.BaseModel):
    path: str
    max_lines: int | None = None

class ReadFileTool(BaseTool):
    name = "read_file"
    description = "Reads a file from the workspace."
    args_schema = ReadFileArgs

    def execute(self, args: ReadFileArgs):
        # ... implementation ...
```

## 3. Automatic Tool Discovery

The `ToolManager` will be updated to automatically discover and register tools from a dedicated directory (e.g., `penguin/tools/available`). This will eliminate the need for manual registration.

## 4. Refactor `ToolManager` and `ActionExecutor`

- The `ToolManager` will be responsible for discovering, loading, and executing tools based on the structured (JSON) input.
- The `ActionExecutor` will be simplified to just parse the action and pass the details to the `ToolManager`, removing the large action map.

This refactoring will result in a more robust, scalable, and maintainable tool system for Penguin.
