# Custom Tools

To add your own tool:

1. Create a Python function or class that performs the action.
2. Expose it through `ToolManager` by updating `tool_manager.py` or registering it via `ToolRegistry`.
3. Provide a name, description and input schema so the language model knows how to call it.
4. Restart Penguin so the new tool is loaded.

Tools placed under `penguin/tools/core` follow this pattern and can be used as references.
