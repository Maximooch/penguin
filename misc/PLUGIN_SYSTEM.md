# Penguin Plugin System

Penguin now features a robust dynamic plugin architecture that enables easy extensibility and modular tool management. This system replaces the previous static tool registration with a flexible plugin-based approach.

## Overview

The plugin system provides:

- **Dynamic Tool Discovery**: Automatically discover tools from plugins directories or Python entry points
- **Hot-loading**: Load and unload plugins at runtime without system restart
- **Modular Architecture**: Clean separation between core system and tools
- **Configuration Management**: Per-plugin configuration and global plugin settings
- **Security**: Plugin sandboxing and permission systems
- **Backward Compatibility**: Legacy tool support during migration

## Architecture

### Core Components

1. **BasePlugin**: Abstract base class for all plugins
2. **PluginManager**: Manages plugin lifecycle and registration
3. **PluginDiscovery**: Discovers plugins from various sources
4. **PluginToolManager**: Plugin-aware tool manager
5. **PluginActionExecutor**: Handles dynamic action execution
6. **PluginConfigManager**: Manages plugin configuration

## Creating Plugins

### Method 1: Class-based Plugin

Create a plugin by inheriting from `BasePlugin`:

```python
from penguin.plugins import BasePlugin, PluginMetadata, ToolDefinition, ParameterSchema

class MyToolsPlugin(BasePlugin):
    def initialize(self) -> bool:
        # Register tools
        search_tool = ToolDefinition(
            name="advanced_search",
            description="Advanced search functionality",
            parameters=[
                ParameterSchema(
                    name="query",
                    type="string",
                    description="Search query",
                    required=True
                ),
                ParameterSchema(
                    name="case_sensitive",
                    type="boolean", 
                    description="Case sensitive search",
                    required=False,
                    default=False
                )
            ],
            handler=self._search_handler,
            category="search",
            tags=["search", "advanced"]
        )
        self.register_tool(search_tool)
        return True
    
    def cleanup(self) -> None:
        # Cleanup resources
        pass
    
    def _search_handler(self, query: str, case_sensitive: bool = False) -> str:
        # Tool implementation
        return f"Search results for: {query} (case_sensitive={case_sensitive})"

# Plugin metadata
PLUGIN_METADATA = PluginMetadata(
    name="my_tools",
    version="1.0.0",
    description="My custom tools plugin",
    author="Your Name"
)

def create_plugin(config=None):
    return MyToolsPlugin(PLUGIN_METADATA, config)
```

### Method 2: Decorator-based Plugin

Use decorators for simpler plugins:

```python
from penguin.plugins import register_tool, register_action

@register_tool(
    name="calculate",
    description="Perform calculations",
    parameters=[
        {"name": "expression", "type": "string", "description": "Math expression", "required": True}
    ],
    category="math"
)
def calculate(expression: str) -> str:
    try:
        result = eval(expression)  # Note: Use safely in production
        return f"Result: {result}"
    except Exception as e:
        return f"Error: {e}"

@register_action(
    name="custom_action",
    description="Handle custom action",
    pattern=r"<custom_action>(.*?)</custom_action>"
)
def handle_custom_action(context):
    return f"Handled custom action: {context}"
```

### Plugin Directory Structure

For directory-based plugins, create this structure:

```
plugins/
└── my_plugin/
    ├── plugin.yml          # Plugin manifest
    ├── main.py            # Plugin implementation
    └── requirements.txt   # Optional dependencies
```

**plugin.yml:**
```yaml
name: my_plugin
version: "1.0.0"
description: "My awesome plugin"
author: "Your Name"
entry_point: "main:MyPlugin"
dependencies:
  - requests>=2.25.0
permissions:
  - network.request
  - filesystem.read
tools:
  - name: my_tool
    description: "My custom tool"
    category: general
config_schema:
  type: object
  properties:
    api_key:
      type: string
      description: "API key for external service"
    max_results:
      type: integer
      default: 10
```

## Plugin Discovery

Plugins are discovered from:

1. **Built-in plugins**: `penguin/tools/plugins/`
2. **User plugins**: `~/.penguin/plugins/`
3. **Project plugins**: `./plugins/` (in current working directory)
4. **Entry points**: Installed packages with `penguin.plugins` entry point

### Entry Point Registration

In your `setup.py` or `pyproject.toml`:

```python
# setup.py
setup(
    name="my-penguin-plugin",
    entry_points={
        "penguin.plugins": [
            "my_plugin = my_package.plugin:MyPlugin",
        ],
    },
)
```

```toml
# pyproject.toml
[project.entry-points."penguin.plugins"]
my_plugin = "my_package.plugin:MyPlugin"
```

## Configuration

### Global Plugin Configuration

Configure the plugin system in `~/.config/penguin/plugins.yml`:

```yaml
# Plugin discovery settings
plugin_directories:
  - "~/.penguin/plugins"
  - "./plugins"
  - "{project_root}/plugins"

auto_discover: true
parallel_loading: true
max_load_workers: 4

# Disabled plugins
disabled_plugins:
  - "problematic_plugin"

# Plugin-specific settings
plugin_settings:
  my_plugin:
    enabled: true
    config:
      api_key: "your-api-key"
      max_results: 20
    permissions:
      - "network.request"
  
  core_tools:
    enabled: true
    priority: 100  # Load first
    config:
      max_command_timeout: 30

# Security settings
allow_user_plugins: true
require_signatures: false
```

### Plugin-specific Configuration

Each plugin can have its own configuration:

```python
class MyPlugin(BasePlugin):
    def initialize(self) -> bool:
        # Access plugin config
        api_key = self.config.get('api_key')
        max_results = self.config.get('max_results', 10)
        
        if not api_key:
            self.logger.error("API key not configured")
            return False
        
        # Use configuration in tools...
        return True
```

## Usage

### Using the Plugin Tool Manager

```python
from penguin.tools.plugin_tool_manager import PluginToolManager

# Initialize with custom plugin directories
tool_manager = PluginToolManager([
    "~/.penguin/plugins",
    "./my_plugins"
])

# List available tools
tools = tool_manager.list_tools()
print(f"Available tools: {tools}")

# Execute a tool
result = tool_manager.execute_tool("my_custom_tool", {
    "input": "test data"
})
print(result)

# Get tool help
help_text = tool_manager.get_tool_help("my_custom_tool")
print(help_text)
```

### Plugin Management

```python
from penguin.plugins import PluginManager

manager = PluginManager()

# Load all plugins
manager.load_all_plugins()

# Load specific plugin
success = manager.load_plugin("my_plugin")

# Unload plugin
manager.unload_plugin("my_plugin")

# Reload plugin (useful for development)
manager.reload_plugin("my_plugin")

# List loaded plugins
plugins = manager.list_plugins()

# Get available tools
tools = manager.get_available_tools()
```

## Migration from Legacy System

The new system maintains backward compatibility. To migrate:

1. **Immediate**: Use `PluginToolManager` instead of `ToolManager`
2. **Gradual**: Convert existing tools to plugins
3. **Complete**: Remove legacy tool dependencies

### Migration Example

Old code:
```python
from penguin.tools import ToolManager

tool_manager = ToolManager()
result = tool_manager.execute_tool("grep_search", {"pattern": "test"})
```

New code:
```python
from penguin.tools.plugin_tool_manager import PluginToolManager

tool_manager = PluginToolManager()
result = tool_manager.execute_tool("grep_search", {"pattern": "test"})
```

## Development and Debugging

### Development Mode

Enable development features in plugin config:

```yaml
dev_mode: true
hot_reload: true
debug_plugins: true
```

### Validation Script

Run the validation script to test the plugin system:

```bash
python scripts/validate_plugin_system.py
```

### Plugin Testing

```python
import pytest
from penguin.plugins import BasePlugin, PluginMetadata

def test_my_plugin():
    metadata = PluginMetadata(
        name="test_plugin",
        version="1.0.0", 
        description="Test plugin"
    )
    
    plugin = MyPlugin(metadata)
    assert plugin.initialize()
    
    # Test tool execution
    result = plugin.execute_tool("my_tool", {"input": "test"})
    assert "test" in result
    
    plugin.cleanup()
```

## Security Considerations

- **Permissions**: Plugins declare required permissions
- **Sandboxing**: Plugins run with limited system access
- **Code Review**: Review third-party plugins before use
- **Signatures**: Enable signature verification for production

```yaml
# Security settings
require_signatures: true
trusted_sources:
  - "official-plugin-repo"
allow_user_plugins: false  # Disable for production
```

## Best Practices

1. **Plugin Design**:
   - Keep plugins focused and single-purpose
   - Use clear, descriptive names
   - Provide comprehensive parameter descriptions
   - Handle errors gracefully

2. **Configuration**:
   - Provide sensible defaults
   - Validate configuration on initialization
   - Document all configuration options

3. **Testing**:
   - Write unit tests for plugin functionality
   - Test error conditions and edge cases
   - Use the validation script regularly

4. **Performance**:
   - Initialize expensive resources lazily
   - Clean up resources in the cleanup method
   - Avoid blocking operations in tool handlers

## Examples

See the following examples:

- **Core Tools Plugin**: `penguin/tools/plugins/core_tools.py`
- **Validation Plugin**: `scripts/validate_plugin_system.py`
- **Plugin Tests**: `tests/test_plugin_system.py`

## API Reference

### BasePlugin

```python
class BasePlugin(ABC):
    def __init__(self, metadata: PluginMetadata, config: Dict[str, Any] = None)
    def initialize(self) -> bool  # Abstract
    def cleanup(self) -> None     # Abstract
    def register_tool(self, tool: ToolDefinition) -> None
    def register_action(self, action: ActionDefinition) -> None
    def execute_tool(self, tool_name: str, parameters: Dict[str, Any]) -> Any
    def execute_action(self, action_name: str, context: Dict[str, Any]) -> Any
```

### PluginManager

```python
class PluginManager:
    def __init__(self, plugin_dirs: List[str] = None, config: Dict = None)
    def discover_plugins(self) -> Dict[str, Dict[str, Any]]
    def load_plugin(self, plugin_name: str) -> bool
    def unload_plugin(self, plugin_name: str) -> bool
    def reload_plugin(self, plugin_name: str) -> bool
    def execute_tool(self, tool_name: str, parameters: Dict[str, Any]) -> Any
    def get_available_tools(self) -> Dict[str, ToolDefinition]
```

### Decorators

```python
@register_tool(name=None, description=None, parameters=None, permissions=None, category="general", tags=None, examples=None)
def my_tool(param1: str, param2: int = 10) -> str:
    pass

@register_action(name=None, description=None, pattern=None, permissions=None)
def my_action(context: Dict[str, Any]) -> Any:
    pass
```

## Troubleshooting

### Common Issues

1. **Plugin not found**: Check plugin directories and manifest files
2. **Import errors**: Verify plugin dependencies are installed
3. **Permission denied**: Check plugin permissions configuration
4. **Tool conflicts**: Ensure unique tool names across plugins

### Debugging

Enable debug logging:

```python
import logging
logging.getLogger('penguin.plugins').setLevel(logging.DEBUG)
```

### Getting Help

- Check the validation script output
- Review plugin logs
- Examine plugin manifest files
- Verify plugin directory structure

## Future Enhancements

- Plugin marketplace integration
- Automatic dependency installation
- Plugin versioning and updates  
- Enhanced security features
- Plugin performance profiling
- Visual plugin management interface

## Contributing

To contribute to the plugin system:

1. Follow the architecture patterns established
2. Add comprehensive tests
3. Update documentation
4. Ensure backward compatibility
5. Run validation scripts before submitting