# RuntimeConfig

The `RuntimeConfig` class provides dynamic configuration management for Penguin, allowing configuration changes without server restarts.

## Overview

`RuntimeConfig` manages runtime-changeable configuration separate from startup configuration, implementing an observer pattern for component synchronization.

## Architecture

```python
from penguin.config import RuntimeConfig

# Initialize with startup config
runtime_config = RuntimeConfig(startup_config)

# Register observers for configuration changes
runtime_config.register_observer(component.on_config_change)

# Change configuration
runtime_config.set_project_root("/new/path")
# All observers are notified automatically
```

## Configuration Properties

### project_root
The current project directory (typically a git repository).

**Initial Value Priority:**
1. `PENGUIN_PROJECT_ROOT` environment variable
2. Auto-detected git root (if `project.root_strategy: git-root`)
3. Current working directory (fallback)

**Changing at Runtime:**
```python
runtime_config.set_project_root("/path/to/project")
```

### workspace_root
The Penguin workspace directory (for conversations, notes, memory).

**Initial Value Priority:**
1. `PENGUIN_WORKSPACE` environment variable
2. `workspace.path` in config file
3. `~/penguin_workspace` (default)

**Changing at Runtime:**
```python
runtime_config.set_workspace_root("/path/to/workspace")
```

### execution_mode
Current execution mode: `project` or `workspace`.

Determines which root directory is used as the active root for file operations.

**Initial Value Priority:**
1. `PENGUIN_WRITE_ROOT` environment variable
2. `defaults.write_root` in config file
3. `project` (default)

**Changing at Runtime:**
```python
runtime_config.set_execution_mode("workspace")
```

### active_root
The currently active root based on execution mode (read-only property).

Returns `project_root` when in project mode, `workspace_root` when in workspace mode.

## Observer Pattern

Components can subscribe to configuration changes to react dynamically:

```python
def on_config_change(config_key: str, new_value: Any) -> None:
    """Called when configuration changes."""
    if config_key == 'project_root':
        # Update internal state
        self.project_root = new_value
        self._refresh_file_map()
    elif config_key == 'execution_mode':
        # Switch modes
        self.mode = new_value
        self._update_active_root()

# Register observer
runtime_config.register_observer(on_config_change)
```

### Observer Callback Signature

```python
Callable[[str, Any], None]
```

**Parameters:**
- `config_key`: The configuration key that changed (`project_root`, `workspace_root`, or `execution_mode`)
- `new_value`: The new value for that key

## Integration with PenguinCore

`PenguinCore` automatically initializes `RuntimeConfig` and registers observers:

```python
class PenguinCore:
    def __init__(
        self,
        config: Optional[Config] = None,
        tool_manager: Optional[ToolManager] = None,
        runtime_config: Optional[RuntimeConfig] = None,
    ):
        # Initialize runtime config
        if runtime_config is None:
            config_dict = config.to_dict() if hasattr(config, 'to_dict') else {}
            self.runtime_config = RuntimeConfig(config_dict)
        else:
            self.runtime_config = runtime_config
        
        # Register tool_manager as observer
        if tool_manager and hasattr(tool_manager, 'on_runtime_config_change'):
            self.runtime_config.register_observer(tool_manager.on_runtime_config_change)
```

## Component Integration

### ToolManager

`ToolManager` subscribes to `RuntimeConfig` and updates its internal state:

```python
def on_runtime_config_change(self, config_key: str, new_value: Any) -> None:
    """React to runtime configuration changes."""
    if config_key == 'project_root':
        self.project_root = str(new_value)
        if self.file_root_mode == 'project':
            self._file_root = self.project_root
            self._refresh_file_map()
    
    elif config_key == 'workspace_root':
        self.workspace_root = str(new_value)
        if self.file_root_mode == 'workspace':
            self._file_root = self.workspace_root
            self._refresh_file_map()
    
    elif config_key == 'execution_mode':
        self.file_root_mode = str(new_value).lower()
        self._file_root = (
            self.project_root if self.file_root_mode == 'project' 
            else self.workspace_root
        )
        self._refresh_file_map()
```

## Error Handling

Configuration changes are validated before applying:

```python
try:
    runtime_config.set_project_root("/nonexistent/path")
except ValueError as e:
    print(f"Invalid path: {e}")
    # ValueError: Project root does not exist: /nonexistent/path
```

**Validation Rules:**
- Paths must exist
- Paths must be directories
- Execution mode must be 'project' or 'workspace'

## Thread Safety

`RuntimeConfig` is **not** thread-safe by default. In multi-threaded environments, wrap calls in a lock:

```python
import threading

config_lock = threading.Lock()

with config_lock:
    runtime_config.set_project_root("/new/path")
```

For async environments, use `asyncio.Lock`:

```python
import asyncio

config_lock = asyncio.Lock()

async with config_lock:
    runtime_config.set_project_root("/new/path")
```

## Export and Persistence

Export current runtime configuration:

```python
config_dict = runtime_config.to_dict()
# {
#   'project_root': '/path/to/project',
#   'workspace_root': '/path/to/workspace',
#   'execution_mode': 'project',
#   'active_root': '/path/to/project'
# }
```

**Note:** Runtime configuration changes are not automatically persisted to config files. To persist changes, manually update your config file or use the CLI config commands.

## API Reference

### Constructor

```python
RuntimeConfig(startup_config: Optional[Dict[str, Any]] = None)
```

Initialize with optional startup configuration dictionary.

### Methods

#### set_project_root
```python
set_project_root(project_root: Union[str, Path]) -> str
```

Change the project root directory.

**Returns:** Success message string

**Raises:** `ValueError` if path is invalid or doesn't exist

#### set_workspace_root
```python
set_workspace_root(workspace_root: Union[str, Path]) -> str
```

Change the workspace root directory.

**Returns:** Success message string

**Raises:** `ValueError` if path is invalid or doesn't exist

#### set_execution_mode
```python
set_execution_mode(mode: str) -> str
```

Switch execution mode between 'project' and 'workspace'.

**Returns:** Success message string

**Raises:** `ValueError` if mode is not 'project' or 'workspace'

#### register_observer
```python
register_observer(callback: Callable[[str, Any], None]) -> None
```

Register a callback to be notified of configuration changes.

#### unregister_observer
```python
unregister_observer(callback: Callable[[str, Any], None]) -> None
```

Unregister a callback.

#### to_dict
```python
to_dict() -> Dict[str, Any]
```

Export current runtime configuration as a dictionary.

## Example: Custom Component

Create a custom component that reacts to configuration changes:

```python
class MyComponent:
    def __init__(self, runtime_config: RuntimeConfig):
        self.runtime_config = runtime_config
        self.project_root = runtime_config.project_root
        
        # Subscribe to changes
        runtime_config.register_observer(self.on_config_change)
    
    def on_config_change(self, config_key: str, new_value: Any) -> None:
        """Handle configuration changes."""
        if config_key == 'project_root':
            print(f"Project root changed to: {new_value}")
            self.project_root = new_value
            self.reload_project_data()
    
    def reload_project_data(self):
        """Reload data based on new project root."""
        # Your implementation here
        pass
```

## See Also

- [Configuration Guide](../configuration.md)
- [API Server Runtime Configuration](api_server.md#runtime-configuration-management)
- [Web API Documentation](api_server.md)

