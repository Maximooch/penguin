# Custom Tools

Penguin's tool system is extensible. New tools can be added under `penguin/tools` and registered with `ToolManager`.

```python
# mytool.py
from penguin.tools.registry import register_tool

@register_tool(name="say_hello", description="Print a greeting", input_schema={})
def say_hello(_: dict) -> str:
    return "Hello from my custom tool!"
```

After creating the module, restart Penguin. The new tool will be available to the language model and via CLI commands.
